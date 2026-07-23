/*
 * ptp-latency.c — Hardware timestamped latency measurement
 *
 * Sends probe packets through a DUT on a dedicated NIC pair and measures
 * one-way latency using PTP hardware timestamps via the kernel
 * SO_TIMESTAMPING API. Designed to run alongside TRex in the crucible
 * trafficgen benchmark, coordinated via POSIX semaphores.
 *
 * Uses AF_PACKET raw sockets with SOF_TIMESTAMPING_TX_HARDWARE and
 * SOF_TIMESTAMPING_RX_HARDWARE to capture MAC-layer timestamps on any
 * NIC with kernel PTP support — no DPDK, no hugepages, no custom builds.
 *
 * -*- mode: c; indent-tabs-mode: nil; c-basic-offset: 4 -*-
 * vim: autoindent tabstop=4 shiftwidth=4 expandtab softtabstop=4 filetype=c
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <signal.h>
#include <getopt.h>
#include <math.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <poll.h>
#include <semaphore.h>
#include <sched.h>
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <net/if.h>
#include <net/ethernet.h>
#include <linux/if_packet.h>
#include <linux/net_tstamp.h>
#include <linux/sockios.h>
#include <arpa/inet.h>
#include <dirent.h>
#include <fcntl.h>
#include <linux/ptp_clock.h>

#define ETHERTYPE_PROBE      0x88B5
#define ETHERTYPE_PTP        0x88F7
#define PROBE_MAGIC          0x50545001
#define MIN_FRAME_LEN        64
#define ETH_HDR_LEN          14
#define PROBE_PAYLOAD_LEN    (MIN_FRAME_LEN - ETH_HDR_LEN - 4)

#define PTP_MSG_SYNC         0x00
#define PTP_VERSION          2
#define PTP_SYNC_LEN         44

#define MAX_FRAME_LEN        9014
#define INITIAL_PROBES       10000000
#define WARMUP_DEFAULT       10
#define PROBE_RATE_DEFAULT   1000
#define TIME_DEFAULT         10

#define TX_TS_TIMEOUT_MS     5
#define RX_TIMEOUT_MS_DEFAULT 5

#define PHC_OFFSET_SAMPLES   5

#define SEM_CHILD_LAUNCH     "trafficgen_child_launch"
#define SEM_CHILD_GO         "trafficgen_child_go"

enum direction {
    DIR_BIDIRECTIONAL,
    DIR_UNIDIRECTIONAL,
    DIR_REVUNIDIRECTIONAL,
};

struct probe_payload {
    uint32_t magic;
    uint32_t seq;
};

struct probe_result {
    double hw_latency_us;
};

struct direction_stats {
    uint32_t tx_count;
    uint32_t rx_count;
    struct probe_result *results;
    uint32_t max_results;
    bool growable;
};

struct ptp_header {
    uint8_t  msg_type;
    uint8_t  version;
    uint16_t msg_length;
    uint8_t  domain;
    uint8_t  reserved1;
    uint16_t flags;
    uint8_t  correction[8];
    uint8_t  reserved2[4];
    uint8_t  source_port_id[10];
    uint16_t seq_id;
    uint8_t  control;
    uint8_t  log_interval;
} __attribute__((packed));

struct iface_info {
    char name[IFNAMSIZ];
    int ifindex;
    uint8_t mac[ETH_ALEN];
    int sock;
    int ptp_fd;
};

struct config {
    char if_a_name[IFNAMSIZ];
    char if_b_name[IFNAMSIZ];
    uint8_t fwd_dst_mac[ETH_ALEN];
    uint8_t rev_dst_mac[ETH_ALEN];
    bool fwd_dst_mac_set;
    bool rev_dst_mac_set;
    int time_secs;
    int probe_rate;
    int warmup_packets;
    bool binarysearch;
    char output_dir[256];
    char fwd_csv[256];
    char rev_csv[256];
    enum direction direction;
    int cpu;
    bool cpu_set;
    bool busy_poll;
    int busy_poll_us;
    bool realtime;
    bool pin_irqs;
    int packet_size;
    bool packet_size_set;
    int max_latency_ms;
};

struct saved_irq {
    int irq_num;
    char orig_affinity[64];
};

struct saved_irq_set {
    struct saved_irq *irqs;
    int count;
    char ifname[IFNAMSIZ];
};

static volatile sig_atomic_t keep_running = 1;
static struct config g_cfg;
static struct iface_info g_if_a, g_if_b;
static struct direction_stats g_fwd, g_rev;
static double g_clock_delta_us = 0.0;
static bool g_ptp_probe_format = false;
static uint16_t g_probe_ethertype = ETHERTYPE_PROBE;
static struct saved_irq_set g_saved_irqs[2];
static int g_saved_irq_count = 0;

static void restore_irq_affinity(void);

static void
signal_handler(int sig)
{
    (void)sig;
    keep_running = 0;
}

static int
cmp_double(const void *a, const void *b)
{
    double da = *(const double *)a;
    double db = *(const double *)b;
    if (da < db) return -1;
    if (da > db) return 1;
    return 0;
}

static int
parse_mac(const char *str, uint8_t *mac)
{
    unsigned int m[6];
    if (sscanf(str, "%x:%x:%x:%x:%x:%x",
               &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) != 6)
        return -1;
    for (int i = 0; i < 6; i++)
        mac[i] = (uint8_t)m[i];
    return 0;
}

static double
ts_to_us(const struct timespec *ts)
{
    return (double)ts->tv_sec * 1e6 + (double)ts->tv_nsec / 1e3;
}

static void
stats_init(struct direction_stats *s, uint32_t max_results)
{
    s->tx_count = 0;
    s->rx_count = 0;
    s->max_results = max_results;
    s->results = calloc(max_results, sizeof(struct probe_result));
    if (!s->results) {
        fprintf(stderr, "ERROR: Failed to allocate results array for %u probes\n",
                max_results);
        exit(1);
    }
}

static int
stats_grow(struct direction_stats *s)
{
    uint32_t new_max = s->max_results * 2;
    struct probe_result *new_results = realloc(s->results,
                                               new_max * sizeof(struct probe_result));
    if (!new_results) {
        fprintf(stderr, "WARNING: Failed to grow results array beyond %u entries\n",
                s->max_results);
        return -1;
    }
    fprintf(stderr, "Growing results array from %u to %u entries\n",
            s->max_results, new_max);
    s->results = new_results;
    s->max_results = new_max;
    return 0;
}

static void
stats_free(struct direction_stats *s)
{
    free(s->results);
    s->results = NULL;
}

static void
output_direction_stats(const char *label, const char *tx_dev, const char *rx_dev,
                       struct direction_stats *s)
{
    fprintf(stderr, "[BS] [%s Latency: %s->%s] %-22s %10u\n",
            label, tx_dev, rx_dev, "TX Samples:", s->tx_count);
    fprintf(stderr, "[BS] [%s Latency: %s->%s] %-22s %10u\n",
            label, tx_dev, rx_dev, "RX Samples:", s->rx_count);

    if (s->tx_count > 0) {
        double loss = (double)(s->tx_count - s->rx_count) / s->tx_count;
        fprintf(stderr, "[BS] [%s Latency: %s->%s] %-22s %17.6f\n",
                label, tx_dev, rx_dev, "Loss Ratio:", loss);
    }

    if (s->rx_count == 0) {
        fprintf(stderr, "[BS] [%s Latency: %s->%s] %-22s %14.3f\n",
                label, tx_dev, rx_dev, "Average:", 0.0);
        return;
    }

    uint32_t n = s->rx_count;
    double *lat = malloc(n * sizeof(double));
    if (!lat) {
        fprintf(stderr, "ERROR: Failed to allocate latency sort array\n");
        return;
    }

    double sum = 0, sum_sq = 0;
    double min_val = 1e18, max_val = -1e18;

    for (uint32_t i = 0; i < n; i++) {
        double v = s->results[i].hw_latency_us;
        lat[i] = v;
        sum += v;
        sum_sq += v * v;
        if (v < min_val) min_val = v;
        if (v > max_val) max_val = v;
    }

    double avg = sum / n;
    double variance = (sum_sq / n) - (avg * avg);
    double stddev = (variance > 0) ? sqrt(variance) : 0;

    qsort(lat, n, sizeof(double), cmp_double);

    double median;
    if (n % 2 == 1)
        median = lat[n / 2];
    else
        median = (lat[n / 2 - 1] + lat[n / 2]) / 2.0;

    struct { const char *field; double val; } metrics[] = {
        {"Average:",  avg},
        {"Median:",   median},
        {"Minimum:",  min_val},
        {"Maximum:",  max_val},
        {"Std. Dev:", stddev},
    };
    for (size_t i = 0; i < sizeof(metrics) / sizeof(metrics[0]); i++) {
        fprintf(stderr, "[BS] [%s Latency: %s->%s] %-22s %14.3f\n",
                label, tx_dev, rx_dev, metrics[i].field, metrics[i].val);
    }

    struct { const char *name; double pct; } pctiles[] = {
        {"50th",      0.50},
        {"95th",      0.95},
        {"99th",      0.99},
        {"99.9th",    0.999},
        {"99.99th",   0.9999},
        {"99.999th",  0.99999},
        {"99.9999th", 0.999999},
    };

    for (size_t i = 0; i < sizeof(pctiles) / sizeof(pctiles[0]); i++) {
        uint32_t idx = (uint32_t)ceil(pctiles[i].pct * n) - 1;
        if (idx >= n) idx = n - 1;
        char field[32];
        snprintf(field, sizeof(field), "%s Percentile:", pctiles[i].name);
        fprintf(stderr, "[BS] [%s Latency: %s->%s] %-22s %14.3f\n",
                label, tx_dev, rx_dev, field, lat[idx]);
    }

    free(lat);
}

static void
write_csv(const char *filename, struct direction_stats *s)
{
    if (strlen(filename) == 0)
        return;

    FILE *f = fopen(filename, "w");
    if (!f) {
        fprintf(stderr, "WARNING: Cannot open CSV file %s: %s\n",
                filename, strerror(errno));
        return;
    }

    fprintf(f, "sample,latency_us\n");
    for (uint32_t i = 0; i < s->rx_count; i++)
        fprintf(f, "%u,%.3f\n", i + 1, s->results[i].hw_latency_us);

    fclose(f);
}

static int
try_hwtstamp_filter(int sock, struct ifreq *ifr, int rx_filter, const char *ifname)
{
    struct hwtstamp_config hwcfg;
    memset(&hwcfg, 0, sizeof(hwcfg));
    hwcfg.tx_type = HWTSTAMP_TX_ON;
    hwcfg.rx_filter = rx_filter;
    ifr->ifr_data = (char *)&hwcfg;

    if (ioctl(sock, SIOCSHWTSTAMP, ifr) < 0)
        return -1;

    fprintf(stderr, "Enabled HW timestamps on %s (tx_type=%d, rx_filter=%d)\n",
            ifname, hwcfg.tx_type, hwcfg.rx_filter);
    return 0;
}

static int
enable_hw_timestamps(const char *ifname)
{
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        fprintf(stderr, "ERROR: socket() for ioctl: %s\n", strerror(errno));
        return -1;
    }

    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);

    if (try_hwtstamp_filter(sock, &ifr, HWTSTAMP_FILTER_ALL, ifname) == 0) {
        close(sock);
        return 0;
    }

    fprintf(stderr, "  FILTER_ALL not supported on %s, trying PTP_V2_EVENT...\n",
            ifname);

    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);

    if (try_hwtstamp_filter(sock, &ifr, HWTSTAMP_FILTER_PTP_V2_EVENT, ifname) == 0) {
        g_ptp_probe_format = true;
        g_probe_ethertype = ETHERTYPE_PTP;
        close(sock);
        return 0;
    }

    fprintf(stderr, "ERROR: No usable HW timestamp filter on %s\n", ifname);
    fprintf(stderr, "  Check with: ethtool -T %s\n", ifname);
    close(sock);
    return -1;
}

static int
open_ptp_device(const char *ifname)
{
    char ptp_dir[256];
    snprintf(ptp_dir, sizeof(ptp_dir), "/sys/class/net/%s/device/ptp", ifname);

    DIR *dir = opendir(ptp_dir);
    if (!dir) {
        fprintf(stderr, "WARNING: No PTP device found for %s: %s\n",
                ifname, strerror(errno));
        return -1;
    }

    struct dirent *entry;
    int fd = -1;
    while ((entry = readdir(dir)) != NULL) {
        if (strncmp(entry->d_name, "ptp", 3) == 0) {
            char dev_path[270];
            snprintf(dev_path, sizeof(dev_path), "/dev/%s", entry->d_name);
            fd = open(dev_path, O_RDONLY);
            if (fd < 0)
                fprintf(stderr, "WARNING: Cannot open %s: %s\n",
                        dev_path, strerror(errno));
            else
                fprintf(stderr, "  PTP device: %s\n", dev_path);
            break;
        }
    }
    closedir(dir);

    if (fd < 0)
        fprintf(stderr, "WARNING: No PTP device entry in %s\n", ptp_dir);

    return fd;
}

static int
setup_interface(struct iface_info *info, const char *ifname)
{
    strncpy(info->name, ifname, IFNAMSIZ - 1);

    info->ifindex = if_nametoindex(ifname);
    if (info->ifindex == 0) {
        fprintf(stderr, "ERROR: Interface %s not found\n", ifname);
        return -1;
    }

    int tmp_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (tmp_sock < 0) {
        fprintf(stderr, "ERROR: socket() for MAC query: %s\n", strerror(errno));
        return -1;
    }

    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);
    if (ioctl(tmp_sock, SIOCGIFHWADDR, &ifr) < 0) {
        fprintf(stderr, "ERROR: SIOCGIFHWADDR on %s: %s\n",
                ifname, strerror(errno));
        close(tmp_sock);
        return -1;
    }
    memcpy(info->mac, ifr.ifr_hwaddr.sa_data, ETH_ALEN);
    close(tmp_sock);

    /* Ensure interface is up */
    tmp_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (tmp_sock < 0) {
        fprintf(stderr, "ERROR: socket(): %s\n", strerror(errno));
        return -1;
    }
    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, ifname, IFNAMSIZ - 1);
    if (ioctl(tmp_sock, SIOCGIFFLAGS, &ifr) < 0) {
        fprintf(stderr, "ERROR: SIOCGIFFLAGS on %s: %s\n",
                ifname, strerror(errno));
        close(tmp_sock);
        return -1;
    }
    if (!(ifr.ifr_flags & IFF_UP)) {
        ifr.ifr_flags |= IFF_UP;
        if (ioctl(tmp_sock, SIOCSIFFLAGS, &ifr) < 0) {
            fprintf(stderr, "ERROR: Failed to bring up %s: %s\n",
                    ifname, strerror(errno));
            close(tmp_sock);
            return -1;
        }
        fprintf(stderr, "Brought up interface %s\n", ifname);
    }
    close(tmp_sock);

    if (enable_hw_timestamps(ifname) < 0)
        return -1;

    info->ptp_fd = open_ptp_device(ifname);

    info->sock = socket(AF_PACKET, SOCK_RAW, htons(g_probe_ethertype));
    if (info->sock < 0) {
        fprintf(stderr, "ERROR: AF_PACKET socket: %s\n", strerror(errno));
        return -1;
    }

    struct sockaddr_ll sll;
    memset(&sll, 0, sizeof(sll));
    sll.sll_family = AF_PACKET;
    sll.sll_protocol = htons(g_probe_ethertype);
    sll.sll_ifindex = info->ifindex;
    if (bind(info->sock, (struct sockaddr *)&sll, sizeof(sll)) < 0) {
        fprintf(stderr, "ERROR: bind() on %s: %s\n", ifname, strerror(errno));
        close(info->sock);
        return -1;
    }

    int ts_flags = SOF_TIMESTAMPING_TX_HARDWARE |
                   SOF_TIMESTAMPING_RX_HARDWARE |
                   SOF_TIMESTAMPING_RAW_HARDWARE;
    if (setsockopt(info->sock, SOL_SOCKET, SO_TIMESTAMPING,
                   &ts_flags, sizeof(ts_flags)) < 0) {
        fprintf(stderr, "ERROR: SO_TIMESTAMPING on %s: %s\n",
                ifname, strerror(errno));
        close(info->sock);
        return -1;
    }

    int one = 1;
    setsockopt(info->sock, SOL_SOCKET, SO_TIMESTAMPNS, &one, sizeof(one));

    fprintf(stderr, "Interface %s: index=%d mac=%02x:%02x:%02x:%02x:%02x:%02x\n",
            ifname, info->ifindex,
            info->mac[0], info->mac[1], info->mac[2],
            info->mac[3], info->mac[4], info->mac[5]);

    return 0;
}

static int
get_hw_timestamp(struct msghdr *msg, struct timespec *hw_ts)
{
    struct cmsghdr *cmsg;
    for (cmsg = CMSG_FIRSTHDR(msg); cmsg; cmsg = CMSG_NXTHDR(msg, cmsg)) {
        if (cmsg->cmsg_level == SOL_SOCKET &&
            cmsg->cmsg_type == SO_TIMESTAMPING) {
            struct timespec *stamps = (struct timespec *)CMSG_DATA(cmsg);
            *hw_ts = stamps[2];
            return 0;
        }
    }
    return -1;
}

static int
build_probe(uint8_t *frame, int frame_size, const uint8_t *dst_mac,
            const uint8_t *src_mac, uint32_t seq)
{
    memset(frame, 0, frame_size);
    memcpy(frame, dst_mac, ETH_ALEN);
    memcpy(frame + ETH_ALEN, src_mac, ETH_ALEN);
    frame[12] = (g_probe_ethertype >> 8) & 0xFF;
    frame[13] = g_probe_ethertype & 0xFF;

    if (g_ptp_probe_format) {
        struct ptp_header *ptp = (struct ptp_header *)(frame + ETH_HDR_LEN);
        ptp->msg_type = PTP_MSG_SYNC;
        ptp->version = PTP_VERSION;
        ptp->msg_length = htons(PTP_SYNC_LEN);
        ptp->seq_id = htons((uint16_t)(seq & 0xFFFF));
        return ETH_HDR_LEN + PTP_SYNC_LEN;
    }

    struct probe_payload *payload = (struct probe_payload *)(frame + ETH_HDR_LEN);
    payload->magic = htonl(PROBE_MAGIC);
    payload->seq = htonl(seq);
    return frame_size - 4;
}

static int
send_probe_and_get_tx_ts(struct iface_info *iface, uint8_t *frame, int frame_len,
                         struct timespec *tx_ts)
{
    struct sockaddr_ll dst;
    memset(&dst, 0, sizeof(dst));
    dst.sll_family = AF_PACKET;
    dst.sll_protocol = htons(g_probe_ethertype);
    dst.sll_ifindex = iface->ifindex;
    dst.sll_halen = ETH_ALEN;
    memcpy(dst.sll_addr, frame, ETH_ALEN);

    ssize_t sent = sendto(iface->sock, frame, frame_len, 0,
                          (struct sockaddr *)&dst, sizeof(dst));
    if (sent < 0) {
        fprintf(stderr, "WARNING: sendto() on %s: %s\n",
                iface->name, strerror(errno));
        return -1;
    }

    struct pollfd pfd = { .fd = iface->sock, .events = POLLPRI | POLLERR };
    int ret = poll(&pfd, 1, TX_TS_TIMEOUT_MS);
    if (ret <= 0) {
        fprintf(stderr, "WARNING: TX timestamp timeout on %s\n", iface->name);
        return -1;
    }

    uint8_t ctrl_buf[256];
    struct iovec iov;
    uint8_t recv_buf[256];
    iov.iov_base = recv_buf;
    iov.iov_len = sizeof(recv_buf);

    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = ctrl_buf;
    msg.msg_controllen = sizeof(ctrl_buf);

    ssize_t n = recvmsg(iface->sock, &msg, MSG_ERRQUEUE);
    if (n < 0) {
        fprintf(stderr, "WARNING: recvmsg(MSG_ERRQUEUE) on %s: %s\n",
                iface->name, strerror(errno));
        return -1;
    }

    if (get_hw_timestamp(&msg, tx_ts) < 0) {
        fprintf(stderr, "WARNING: No HW timestamp in TX error queue on %s\n",
                iface->name);
        return -1;
    }

    return 0;
}

static uint32_t g_src_mac_mismatch_count = 0;

static int
recv_probe_with_rx_ts(struct iface_info *iface, struct timespec *rx_ts,
                      uint32_t expected_seq, const uint8_t *expected_src_mac)
{
    struct pollfd pfd = { .fd = iface->sock, .events = POLLIN };
    int ret = poll(&pfd, 1, g_cfg.max_latency_ms);
    if (ret <= 0)
        return -1;

    uint8_t frame[MAX_FRAME_LEN];
    uint8_t ctrl_buf[256];
    struct iovec iov = { .iov_base = frame, .iov_len = sizeof(frame) };

    struct msghdr msg;
    memset(&msg, 0, sizeof(msg));
    msg.msg_iov = &iov;
    msg.msg_iovlen = 1;
    msg.msg_control = ctrl_buf;
    msg.msg_controllen = sizeof(ctrl_buf);

    ssize_t n = recvmsg(iface->sock, &msg, 0);
    if (n < (ssize_t)(ETH_HDR_LEN + 8))
        return -1;

    uint16_t ethertype = (frame[12] << 8) | frame[13];
    if (ethertype != g_probe_ethertype)
        return -1;

    if (expected_src_mac && memcmp(frame + ETH_ALEN, expected_src_mac, ETH_ALEN) != 0) {
        if (g_src_mac_mismatch_count == 0) {
            fprintf(stderr, "WARNING: RX source MAC mismatch on %s: "
                    "expected %02x:%02x:%02x:%02x:%02x:%02x, "
                    "got %02x:%02x:%02x:%02x:%02x:%02x\n",
                    iface->name,
                    expected_src_mac[0], expected_src_mac[1],
                    expected_src_mac[2], expected_src_mac[3],
                    expected_src_mac[4], expected_src_mac[5],
                    frame[6], frame[7], frame[8],
                    frame[9], frame[10], frame[11]);
        }
        g_src_mac_mismatch_count++;
        return -1;
    }

    if (g_ptp_probe_format) {
        struct ptp_header *ptp = (struct ptp_header *)(frame + ETH_HDR_LEN);
        if (ptp->msg_type != PTP_MSG_SYNC || ptp->version != PTP_VERSION)
            return -1;
        if (expected_seq > 0 && ntohs(ptp->seq_id) != (uint16_t)(expected_seq & 0xFFFF))
            return -1;
    } else {
        struct probe_payload *payload = (struct probe_payload *)(frame + ETH_HDR_LEN);
        if (ntohl(payload->magic) != PROBE_MAGIC)
            return -1;
        if (expected_seq > 0 && ntohl(payload->seq) != expected_seq)
            return -1;
    }

    if (get_hw_timestamp(&msg, rx_ts) < 0)
        return -1;

    return 0;
}

static void
drain_rx(struct iface_info *iface)
{
    uint8_t buf[MAX_FRAME_LEN];
    struct pollfd pfd = { .fd = iface->sock, .events = POLLIN };

    while (poll(&pfd, 1, 10) > 0)
        recv(iface->sock, buf, sizeof(buf), MSG_DONTWAIT);
}

static int
set_cpu_affinity(int cpu)
{
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(cpu, &cpuset);

    if (sched_setaffinity(0, sizeof(cpuset), &cpuset) < 0) {
        fprintf(stderr, "ERROR: sched_setaffinity to CPU %d: %s\n",
                cpu, strerror(errno));
        return -1;
    }

    fprintf(stderr, "Pinned process to CPU %d\n", cpu);
    return 0;
}

static int
set_realtime_priority(void)
{
    struct sched_param param;
    param.sched_priority = 1;

    if (sched_setscheduler(0, SCHED_FIFO, &param) < 0) {
        fprintf(stderr, "WARNING: sched_setscheduler SCHED_FIFO: %s (continuing without realtime priority)\n",
                strerror(errno));
        return -1;
    }

    fprintf(stderr, "Set SCHED_FIFO priority %d\n", param.sched_priority);
    return 0;
}

static void
enable_busy_poll(struct iface_info *iface, int busy_poll_us)
{
    int val = busy_poll_us;
    if (setsockopt(iface->sock, SOL_SOCKET, SO_BUSY_POLL,
                   &val, sizeof(val)) < 0) {
        fprintf(stderr, "WARNING: SO_BUSY_POLL on %s: %s\n",
                iface->name, strerror(errno));
        return;
    }

    val = 1;
    setsockopt(iface->sock, SOL_SOCKET, SO_PREFER_BUSY_POLL,
               &val, sizeof(val));

    val = 8;
    setsockopt(iface->sock, SOL_SOCKET, SO_BUSY_POLL_BUDGET,
               &val, sizeof(val));

    fprintf(stderr, "Enabled SO_BUSY_POLL (%d us) on %s\n",
            busy_poll_us, iface->name);
}

static void
pin_irqs_to_cpu(const char *ifname, int cpu)
{
    char path[256];

    snprintf(path, sizeof(path), "/sys/class/net/%s/device/msi_irqs", ifname);
    DIR *dir = opendir(path);
    if (!dir) {
        fprintf(stderr, "WARNING: Cannot read IRQs for %s: %s\n",
                ifname, strerror(errno));
        return;
    }

    /* Count IRQs first */
    int total = 0;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (entry->d_name[0] == '.')
            continue;
        total++;
    }
    rewinddir(dir);

    struct saved_irq_set *set = &g_saved_irqs[g_saved_irq_count];
    snprintf(set->ifname, sizeof(set->ifname), "%s", ifname);
    set->irqs = calloc(total, sizeof(struct saved_irq));
    set->count = 0;

    if (!set->irqs) {
        fprintf(stderr, "WARNING: Cannot allocate IRQ save state for %s\n", ifname);
        closedir(dir);
        return;
    }

    int pinned = 0;
    while ((entry = readdir(dir)) != NULL) {
        if (entry->d_name[0] == '.')
            continue;

        int irq_num = atoi(entry->d_name);
        char affinity_path[512];
        snprintf(affinity_path, sizeof(affinity_path),
                 "/proc/irq/%s/smp_affinity_list", entry->d_name);

        /* Save original affinity */
        FILE *f = fopen(affinity_path, "r");
        if (f) {
            char orig[64] = "";
            if (fgets(orig, sizeof(orig), f)) {
                orig[strcspn(orig, "\n")] = '\0';
                set->irqs[set->count].irq_num = irq_num;
                snprintf(set->irqs[set->count].orig_affinity,
                         sizeof(set->irqs[set->count].orig_affinity),
                         "%s", orig);
                set->count++;
            }
            fclose(f);
        }

        /* Pin to target CPU */
        f = fopen(affinity_path, "w");
        if (f) {
            fprintf(f, "%d\n", cpu);
            fclose(f);
            pinned++;
        }
    }

    closedir(dir);
    g_saved_irq_count++;
    fprintf(stderr, "Pinned %d IRQs for %s to CPU %d (saved %d original affinities)\n",
            pinned, ifname, cpu, set->count);
}

static void
restore_irq_affinity(void)
{
    for (int i = 0; i < g_saved_irq_count; i++) {
        struct saved_irq_set *set = &g_saved_irqs[i];
        int restored = 0;

        for (int j = 0; j < set->count; j++) {
            char affinity_path[512];
            snprintf(affinity_path, sizeof(affinity_path),
                     "/proc/irq/%d/smp_affinity_list", set->irqs[j].irq_num);

            FILE *f = fopen(affinity_path, "w");
            if (f) {
                fprintf(f, "%s\n", set->irqs[j].orig_affinity);
                fclose(f);
                restored++;
            }
        }

        fprintf(stderr, "Restored %d/%d IRQ affinities for %s\n",
                restored, set->count, set->ifname);
        free(set->irqs);
        set->irqs = NULL;
        set->count = 0;
    }
    g_saved_irq_count = 0;
}

static int
run_one_probe(struct iface_info *tx_iface, struct iface_info *rx_iface,
              const uint8_t *dst_mac, uint32_t seq, int frame_size,
              struct direction_stats *stats, double clock_correction_us)
{
    uint8_t frame[MAX_FRAME_LEN];
    int frame_len = build_probe(frame, frame_size, dst_mac, tx_iface->mac, seq);

    struct timespec tx_ts, rx_ts;

    if (send_probe_and_get_tx_ts(tx_iface, frame, frame_len, &tx_ts) < 0) {
        if (stats) stats->tx_count++;
        return -1;
    }

    if (stats) stats->tx_count++;

    if (recv_probe_with_rx_ts(rx_iface, &rx_ts, seq, tx_iface->mac) < 0)
        return -1;

    double latency_us = ts_to_us(&rx_ts) - ts_to_us(&tx_ts) + clock_correction_us;

    if (stats) {
        if (stats->rx_count >= stats->max_results) {
            if (!stats->growable || stats_grow(stats) < 0)
                return -2;
        }
        stats->results[stats->rx_count].hw_latency_us = latency_us;
        stats->rx_count++;
    }

    return 0;
}

static double
get_phc_offset_us(int ptp_fd, const char *ifname)
{
    struct ptp_sys_offset_precise precise;
    memset(&precise, 0, sizeof(precise));

    if (ioctl(ptp_fd, PTP_SYS_OFFSET_PRECISE, &precise) == 0) {
        double phc_us = precise.device.sec * 1e6 + precise.device.nsec / 1e3;
        double sys_us = precise.sys_realtime.sec * 1e6 +
                        precise.sys_realtime.nsec / 1e3;
        return phc_us - sys_us;
    }

    /* Fall back to PTP_SYS_OFFSET with bracketing */
    struct ptp_sys_offset offset;
    memset(&offset, 0, sizeof(offset));
    offset.n_samples = PHC_OFFSET_SAMPLES;

    if (ioctl(ptp_fd, PTP_SYS_OFFSET, &offset) < 0) {
        fprintf(stderr, "WARNING: PTP_SYS_OFFSET failed on %s: %s\n",
                ifname, strerror(errno));
        return 0.0;
    }

    double best_delta = 0.0;
    double best_interval = 1e18;
    for (unsigned int i = 0; i < offset.n_samples; i++) {
        struct ptp_clock_time *sys1 = &offset.ts[2 * i];
        struct ptp_clock_time *phc  = &offset.ts[2 * i + 1];
        struct ptp_clock_time *sys2 = &offset.ts[2 * i + 2];

        double s1 = sys1->sec * 1e6 + sys1->nsec / 1e3;
        double p  = phc->sec  * 1e6 + phc->nsec  / 1e3;
        double s2 = sys2->sec * 1e6 + sys2->nsec / 1e3;

        double interval = s2 - s1;
        if (interval < best_interval) {
            best_interval = interval;
            best_delta = p - (s1 + s2) / 2.0;
        }
    }

    return best_delta;
}

static double
calibrate_clock_offset(void)
{
    if (g_if_a.ptp_fd < 0 || g_if_b.ptp_fd < 0) {
        fprintf(stderr, "WARNING: PTP devices not available, assuming zero clock offset\n");
        return 0.0;
    }

    fprintf(stderr, "Calibrating clock offset via PTP hardware clocks...\n");

    double offset_a = get_phc_offset_us(g_if_a.ptp_fd, g_if_a.name);
    double offset_b = get_phc_offset_us(g_if_b.ptp_fd, g_if_b.name);
    double delta = offset_a - offset_b;

    fprintf(stderr, "Clock calibration: PHC_A-sys=%.3f us, PHC_B-sys=%.3f us, delta=%.3f us\n",
            offset_a, offset_b, delta);

    return delta;
}

static void
parse_args(int argc, char **argv)
{
    static struct option long_opts[] = {
        {"if-a",              required_argument, NULL, 'a'},
        {"if-b",              required_argument, NULL, 'b'},
        {"fwd-dst-mac",       required_argument, NULL, 'F'},
        {"rev-dst-mac",       required_argument, NULL, 'R'},
        {"time",              required_argument, NULL, 't'},
        {"probe-rate",        required_argument, NULL, 'r'},
        {"warmup-packets",    required_argument, NULL, 'w'},
        {"binarysearch",      no_argument,       NULL, 'B'},
        {"output",            required_argument, NULL, 'o'},
        {"fwdfile",           required_argument, NULL, 'f'},
        {"revfile",           required_argument, NULL, 'v'},
        {"traffic-direction", required_argument, NULL, 'd'},
        {"cpu",               required_argument, NULL, 'c'},
        {"busy-poll",         optional_argument, NULL, 'p'},
        {"realtime",          no_argument,       NULL, 'T'},
        {"max-latency",       required_argument, NULL, 'm'},
        {"packet-size",       required_argument, NULL, 's'},
        {"pin-irqs",          no_argument,       NULL, 'I'},
        {"help",              no_argument,       NULL, 'h'},
        {NULL, 0, NULL, 0},
    };

    g_cfg.time_secs = TIME_DEFAULT;
    g_cfg.probe_rate = PROBE_RATE_DEFAULT;
    g_cfg.warmup_packets = WARMUP_DEFAULT;
    g_cfg.direction = DIR_BIDIRECTIONAL;
    g_cfg.packet_size = MIN_FRAME_LEN;
    g_cfg.max_latency_ms = RX_TIMEOUT_MS_DEFAULT;
    g_cfg.busy_poll_us = 50;

    int opt;
    while ((opt = getopt_long(argc, argv, "a:b:F:R:t:r:w:Bm:o:f:v:d:s:c:p::TIh",
                              long_opts, NULL)) != -1) {
        switch (opt) {
        case 'a':
            strncpy(g_cfg.if_a_name, optarg, IFNAMSIZ - 1);
            break;
        case 'b':
            strncpy(g_cfg.if_b_name, optarg, IFNAMSIZ - 1);
            break;
        case 'F':
            if (parse_mac(optarg, g_cfg.fwd_dst_mac) < 0) {
                fprintf(stderr, "ERROR: Invalid MAC: %s\n", optarg);
                exit(1);
            }
            g_cfg.fwd_dst_mac_set = true;
            break;
        case 'R':
            if (parse_mac(optarg, g_cfg.rev_dst_mac) < 0) {
                fprintf(stderr, "ERROR: Invalid MAC: %s\n", optarg);
                exit(1);
            }
            g_cfg.rev_dst_mac_set = true;
            break;
        case 't':
            g_cfg.time_secs = atoi(optarg);
            break;
        case 'r':
            g_cfg.probe_rate = atoi(optarg);
            break;
        case 'w':
            g_cfg.warmup_packets = atoi(optarg);
            break;
        case 'B':
            g_cfg.binarysearch = true;
            break;
        case 'm':
            g_cfg.max_latency_ms = atoi(optarg);
            if (g_cfg.max_latency_ms <= 0) {
                fprintf(stderr, "ERROR: --max-latency must be a positive integer (ms)\n");
                exit(1);
            }
            break;
        case 'o':
            strncpy(g_cfg.output_dir, optarg, sizeof(g_cfg.output_dir) - 1);
            break;
        case 'f':
            strncpy(g_cfg.fwd_csv, optarg, sizeof(g_cfg.fwd_csv) - 1);
            break;
        case 'v':
            strncpy(g_cfg.rev_csv, optarg, sizeof(g_cfg.rev_csv) - 1);
            break;
        case 'd':
            if (strcmp(optarg, "uni") == 0)
                g_cfg.direction = DIR_UNIDIRECTIONAL;
            else if (strcmp(optarg, "revuni") == 0)
                g_cfg.direction = DIR_REVUNIDIRECTIONAL;
            else
                g_cfg.direction = DIR_BIDIRECTIONAL;
            break;
        case 's':
            g_cfg.packet_size = atoi(optarg);
            g_cfg.packet_size_set = true;
            if (g_cfg.packet_size < MIN_FRAME_LEN || g_cfg.packet_size > MAX_FRAME_LEN) {
                fprintf(stderr, "ERROR: --packet-size must be between %d and %d\n",
                        MIN_FRAME_LEN, MAX_FRAME_LEN);
                exit(1);
            }
            break;
        case 'c':
            g_cfg.cpu = atoi(optarg);
            g_cfg.cpu_set = true;
            break;
        case 'p':
            g_cfg.busy_poll = true;
            if (optarg)
                g_cfg.busy_poll_us = atoi(optarg);
            break;
        case 'T':
            g_cfg.realtime = true;
            break;
        case 'I':
            g_cfg.pin_irqs = true;
            break;
        case 'h':
            printf("Usage: ptp-latency --if-a IFACE --if-b IFACE [options]\n"
                   "\n"
                   "Required:\n"
                   "  --if-a IFACE           TX interface for forward direction\n"
                   "  --if-b IFACE           RX interface for forward direction\n"
                   "\n"
                   "Options:\n"
                   "  --fwd-dst-mac MAC      Destination MAC for forward probes\n"
                   "  --rev-dst-mac MAC      Destination MAC for reverse probes\n"
                   "  --time SECONDS         Measurement duration (default: %d)\n"
                   "  --probe-rate PPS       Probes per second, 0=max (default: %d)\n"
                   "  --warmup-packets N     Warmup probes (default: %d)\n"
                   "  --binarysearch         Enable POSIX semaphore IPC\n"
                   "  --output DIR           Output directory for CSV files\n"
                   "  --fwdfile FILE         Forward latency CSV filename\n"
                   "  --revfile FILE         Reverse latency CSV filename\n"
                   "  --max-latency MS       RX timeout in milliseconds (default: %d)\n"
                   "  --packet-size BYTES    Probe frame size in bytes (default: %d, raw format only)\n"
                   "  --traffic-direction D  bi, uni, or revuni (default: bi)\n"
                   "\n"
                   "Tuning:\n"
                   "  --cpu N                Pin process to CPU N\n"
                   "  --busy-poll[=US]       Enable SO_BUSY_POLL (default: %d us)\n"
                   "  --realtime             Use SCHED_FIFO realtime priority\n"
                   "  --pin-irqs             Pin NIC IRQs to --cpu (requires --cpu)\n"
                   "\n"
                   "  --help                 Show this help\n",
                   RX_TIMEOUT_MS_DEFAULT,
                   MIN_FRAME_LEN,
                   TIME_DEFAULT, PROBE_RATE_DEFAULT, WARMUP_DEFAULT,
                   50);
            exit(0);
        default:
            exit(1);
        }
    }

    if (strlen(g_cfg.if_a_name) == 0 || strlen(g_cfg.if_b_name) == 0) {
        fprintf(stderr, "ERROR: --if-a and --if-b are required\n");
        exit(1);
    }
}

static int
run_measurement(void)
{
    bool do_fwd = (g_cfg.direction == DIR_BIDIRECTIONAL ||
                   g_cfg.direction == DIR_UNIDIRECTIONAL);
    bool do_rev = (g_cfg.direction == DIR_BIDIRECTIONAL ||
                   g_cfg.direction == DIR_REVUNIDIRECTIONAL);

    bool growable;
    uint32_t max_probes;
    if (g_cfg.probe_rate > 0 && g_cfg.time_secs > 0) {
        max_probes = (uint32_t)g_cfg.time_secs * g_cfg.probe_rate;
        growable = false;
    } else {
        max_probes = INITIAL_PROBES;
        growable = true;
    }

    if (do_fwd) { stats_init(&g_fwd, max_probes); g_fwd.growable = growable; }
    if (do_rev) { stats_init(&g_rev, max_probes); g_rev.growable = growable; }

    uint8_t *fwd_dst = g_cfg.fwd_dst_mac_set ? g_cfg.fwd_dst_mac : g_if_b.mac;
    uint8_t *rev_dst = g_cfg.rev_dst_mac_set ? g_cfg.rev_dst_mac : g_if_a.mac;

    drain_rx(&g_if_a);
    drain_rx(&g_if_b);

    fprintf(stderr, "Sending %d warmup probes...\n", g_cfg.warmup_packets);
    for (int i = 0; i < g_cfg.warmup_packets && keep_running; i++) {
        if (do_fwd)
            run_one_probe(&g_if_a, &g_if_b, fwd_dst, 0, g_cfg.packet_size, NULL, 0.0);
        if (do_rev)
            run_one_probe(&g_if_b, &g_if_a, rev_dst, 0, g_cfg.packet_size, NULL, 0.0);
        usleep(1000);
    }

    if (do_fwd && do_rev)
        g_clock_delta_us = calibrate_clock_offset();

    if (g_cfg.binarysearch) {
        sem_t *launch_sem = sem_open(SEM_CHILD_LAUNCH, 0);
        sem_t *go_sem = sem_open(SEM_CHILD_GO, 0);

        if (launch_sem == SEM_FAILED || go_sem == SEM_FAILED) {
            fprintf(stderr, "ERROR: Failed to open semaphores: %s\n",
                    strerror(errno));
            return -1;
        }

        fprintf(stderr, "Signaling ready to binary-search.py\n");
        sem_post(launch_sem);

        fprintf(stderr, "Waiting for go signal...\n");
        sem_wait(go_sem);

        sem_close(launch_sem);
        sem_close(go_sem);

        fprintf(stderr, "Go signal received, starting measurement\n");
    }

    drain_rx(&g_if_a);
    drain_rx(&g_if_b);

    uint64_t probe_interval_us = g_cfg.probe_rate > 0 ?
                                 1000000 / g_cfg.probe_rate : 0;
    uint32_t seq = 1;
    bool timed_run = (g_cfg.time_secs > 0);

    struct timespec start_ts;
    clock_gettime(CLOCK_MONOTONIC, &start_ts);
    uint64_t start_us = (uint64_t)start_ts.tv_sec * 1000000 +
                        start_ts.tv_nsec / 1000;
    uint64_t duration_us = (uint64_t)g_cfg.time_secs * 1000000;

    if (timed_run) {
        if (g_cfg.probe_rate > 0)
            fprintf(stderr, "Measuring for %d seconds at %d probes/sec...\n",
                    g_cfg.time_secs, g_cfg.probe_rate);
        else
            fprintf(stderr, "Measuring for %d seconds at maximum rate...\n",
                    g_cfg.time_secs);
    } else {
        if (g_cfg.probe_rate > 0)
            fprintf(stderr, "Measuring indefinitely at %d probes/sec (stop with SIGINT)...\n",
                    g_cfg.probe_rate);
        else
            fprintf(stderr, "Measuring indefinitely at maximum rate (stop with SIGINT)...\n");
    }

    while (keep_running) {
        if (timed_run) {
            struct timespec now_ts;
            clock_gettime(CLOCK_MONOTONIC, &now_ts);
            uint64_t now_us = (uint64_t)now_ts.tv_sec * 1000000 +
                              now_ts.tv_nsec / 1000;
            if (now_us - start_us >= duration_us)
                break;
        }

        if (do_fwd) {
            int rc = run_one_probe(&g_if_a, &g_if_b, fwd_dst, seq,
                                   g_cfg.packet_size, &g_fwd, -g_clock_delta_us);
            seq++;
            if (rc == -2) {
                fprintf(stderr, "ERROR: Memory exhaustion, stopping measurement\n");
                break;
            }
        }

        if (do_rev) {
            int rc = run_one_probe(&g_if_b, &g_if_a, rev_dst, seq,
                                   g_cfg.packet_size, &g_rev, g_clock_delta_us);
            seq++;
            if (rc == -2) {
                fprintf(stderr, "ERROR: Memory exhaustion, stopping measurement\n");
                break;
            }
        }

        if (probe_interval_us > 0)
            usleep(probe_interval_us);
    }

    fprintf(stderr, "\nMeasurement complete.\n");

    if (do_fwd) {
        output_direction_stats("Forward", g_if_a.name, g_if_b.name, &g_fwd);
        if (strlen(g_cfg.fwd_csv) > 0) {
            char path[512];
            if (strlen(g_cfg.output_dir) > 0)
                snprintf(path, sizeof(path), "%s/%s", g_cfg.output_dir, g_cfg.fwd_csv);
            else
                strncpy(path, g_cfg.fwd_csv, sizeof(path) - 1);
            write_csv(path, &g_fwd);
        }
    }

    if (do_rev) {
        output_direction_stats("Reverse", g_if_b.name, g_if_a.name, &g_rev);
        if (strlen(g_cfg.rev_csv) > 0) {
            char path[512];
            if (strlen(g_cfg.output_dir) > 0)
                snprintf(path, sizeof(path), "%s/%s", g_cfg.output_dir, g_cfg.rev_csv);
            else
                strncpy(path, g_cfg.rev_csv, sizeof(path) - 1);
            write_csv(path, &g_rev);
        }
    }

    if (g_src_mac_mismatch_count > 0)
        fprintf(stderr, "WARNING: %u packets received with unexpected source MAC (possible L2 forwarding issue)\n",
                g_src_mac_mismatch_count);

    if (do_fwd) stats_free(&g_fwd);
    if (do_rev) stats_free(&g_rev);

    return 0;
}

int
main(int argc, char **argv)
{
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    parse_args(argc, argv);

    fprintf(stderr, "ptp-latency: kernel SO_TIMESTAMPING hardware latency measurement\n");
    fprintf(stderr, "  Interface A: %s\n", g_cfg.if_a_name);
    fprintf(stderr, "  Interface B: %s\n", g_cfg.if_b_name);

    if (setup_interface(&g_if_a, g_cfg.if_a_name) < 0)
        return 1;
    if (setup_interface(&g_if_b, g_cfg.if_b_name) < 0)
        return 1;

    fprintf(stderr, "  Probe format: %s (EtherType 0x%04X)\n",
            g_ptp_probe_format ? "PTP Sync" : "raw", g_probe_ethertype);

    if (!g_ptp_probe_format)
        fprintf(stderr, "  Packet size: %d bytes\n", g_cfg.packet_size);

    if (g_ptp_probe_format && g_cfg.packet_size_set) {
        fprintf(stderr, "ERROR: --packet-size cannot be used with PTP Sync probe format\n");
        fprintf(stderr, "  The NIC does not support HWTSTAMP_FILTER_ALL, so probes must use\n");
        fprintf(stderr, "  the fixed-size PTP Sync format for hardware timestamping.\n");
        return 1;
    }

    if (!g_cfg.fwd_dst_mac_set) {
        memcpy(g_cfg.fwd_dst_mac, g_if_b.mac, ETH_ALEN);
        fprintf(stderr, "  Forward dst MAC: %02x:%02x:%02x:%02x:%02x:%02x (from %s)\n",
                g_cfg.fwd_dst_mac[0], g_cfg.fwd_dst_mac[1],
                g_cfg.fwd_dst_mac[2], g_cfg.fwd_dst_mac[3],
                g_cfg.fwd_dst_mac[4], g_cfg.fwd_dst_mac[5],
                g_if_b.name);
    }
    if (!g_cfg.rev_dst_mac_set) {
        memcpy(g_cfg.rev_dst_mac, g_if_a.mac, ETH_ALEN);
        fprintf(stderr, "  Reverse dst MAC: %02x:%02x:%02x:%02x:%02x:%02x (from %s)\n",
                g_cfg.rev_dst_mac[0], g_cfg.rev_dst_mac[1],
                g_cfg.rev_dst_mac[2], g_cfg.rev_dst_mac[3],
                g_cfg.rev_dst_mac[4], g_cfg.rev_dst_mac[5],
                g_if_a.name);
    }

    if (g_cfg.cpu_set) {
        if (set_cpu_affinity(g_cfg.cpu) < 0)
            return 1;
        if (g_cfg.pin_irqs) {
            pin_irqs_to_cpu(g_cfg.if_a_name, g_cfg.cpu);
            pin_irqs_to_cpu(g_cfg.if_b_name, g_cfg.cpu);
        }
    } else if (g_cfg.pin_irqs) {
        fprintf(stderr, "ERROR: --pin-irqs requires --cpu\n");
        return 1;
    }

    if (g_cfg.realtime)
        set_realtime_priority();

    if (g_cfg.busy_poll) {
        enable_busy_poll(&g_if_a, g_cfg.busy_poll_us);
        enable_busy_poll(&g_if_b, g_cfg.busy_poll_us);
    }

    int ret = run_measurement();

    if (g_saved_irq_count > 0)
        restore_irq_affinity();

    close(g_if_a.sock);
    close(g_if_b.sock);
    if (g_if_a.ptp_fd >= 0) close(g_if_a.ptp_fd);
    if (g_if_b.ptp_fd >= 0) close(g_if_b.ptp_fd);

    return ret;
}
