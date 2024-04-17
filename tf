diff --cc multiplex.json
index b35d8c1,84467ec..0000000
--- a/multiplex.json
+++ b/multiplex.json
@@@ -92,7 -92,7 +92,7 @@@
  	},
  	"mac_address_list": {
  	    "description": "1 or more (comma separated) list of mac addresses",
--	    "args": [ "src-macs", "dst-macs", "encap-dst-macs", "encap-src-macs" ],
++	    "args": [ "src-macs", "dst-macs", "encap-dst-macs", "encap-src-macs", "testpmd-dst-macs" ],
  	    "vals": [ "^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}(,([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2})*$" ]
  	},
  	"ip_address_list": {
diff --git a/trafficgen-server-start b/trafficgen-server-start
index dc28170..f68142e 100755
--- a/trafficgen-server-start
+++ b/trafficgen-server-start
@@ -24,6 +24,7 @@ testpmd_enable_rss_udp="off"
 testpmd_devopt=""
 testpmd_mbuf_size=""
 testpmd_burst=""
+testpmd_dst_macs=""
 
 # Options processing
 re='^(--[^=]+)=([^=]+)'
@@ -85,6 +86,9 @@ while [ $# -gt 0 ]; do
         --testpmd-burst)
             testpmd_burst="$val"
             ;;
+        --testpmd-dst-macs)
+            testpmd_dst_macs="$val"
+            ;;
     esac
 done
 
@@ -109,8 +113,16 @@ if [ "$switch_type" == "testpmd" ]; then
             echo "Found eth-peer MAC1 $peermac1"
         fi
     fi
-    peermac0="1c:34:da:77:3e:80"
-    peermac1="1c:34:da:77:3e:81"
+
+    if [ ! -z "$testpmd_dst_macs" ]; then
+    	# Hard-coded MACs for multi-VM test for perf8/perf188
+    	#peermac0="1c:34:da:77:3e:80"
+    	#peermac1="1c:34:da:77:3e:81"
+
+	peermac0=`echo $testpmd_dst_macs | awk -F, '{print $1}'`
+	peermac1=`echo $testpmd_dst_macs | awk -F, '{print $2}'`
+    fi
+
 
     # Build testpmd cmdline opts for device selection
     echo "Resolving devices for testpmd based on devices [$devices]"
@@ -357,7 +369,7 @@ if [ "$switch_type" == "testpmd" ]; then
     if [ "$testpmd_forward_mode" == "mac" ]; then
         # TODO: use regex instead:
         if [ -z "$peermac0" -o -z "$peermac1" ]; then
-            exit_error  "[ERROR] Using forware-mode = mac, but did not get MAC addresses from TREX" 1 "$sample_dir"
+            exit_error  "[ERROR] Using forware-mode = mac, but did not get MAC addresses from TREX or --testpmd-dst-macs" 1 "$sample_dir"
         fi
         testpmd_opts+=" --eth-peer 0,$peermac0 --eth-peer 1,$peermac1 --forward-mode mac"
     else
