#!/bin/bash

force_install=0

opts=$(getopt -q -o -c: --longoptions "force" -n "getopt.sh" -- "$@")
if [ $? -ne 0 ]; then
    printf -- "$*\n"
    printf -- "\n"
    printf -- "\tThe following options are available:\n\n"
    printf -- "\n"
    printf -- "--force\n"
    printf -- "  Download and build MoonGen even if it is already present.\n"
    exit 1
fi

eval set -- "$opts"
while true; do
    case "${1}" in
        force)
        shift
        force_install=1
        ;;
    --)
        break
        ;;
    *)
        if [ -n "${1}" ]; then
            echo "ERROR: Unrecognized option ${1}"
        fi
        exit 1
        ;;
    esac
done

tg_dir=`readlink -f $(dirname $0)`

# private MoonGen repo
moongen_url="https://github.com/perftool-incubator/MoonGen.git"

# private lua-luaipc repo
luaipc_url="https://github.com/perftool-incubator/lua-luaipc.git"

moongen_dir="MoonGen"
luaipc_dir="lua-luaipc"

if pushd ${tg_dir} > /dev/null; then
    if [ -d ${moongen_dir} -a "${force_install}" == "0" ]; then
        echo "MoonGen already installed"
    else
        # install distro moongen dependencies
	posix_ipc_installed=0
	for pip_version in pip3.9 pip3; do
            if command -v ${pip_version} > /dev/null; then
		if ! ${pip_version} install --user posix_ipc; then
                    echo "ERROR: Failed to install posix_ipc via ${pip_version}"
                    exit 1
		else
		    posix_ipc_installed=1
		    break
		fi
	    else
		echo "WARNING: ${pip_version} not found"
            fi
	done
	if [ "${posix_ipc_installed}" == "0" ]; then
	    echo "ERROR: Could not install posix_ipc"
	    exit 1
	fi

        if [ -d ${moongen_dir} ]; then
             /bin/rm -Rf ${moongen_dir}
        fi

        git clone ${moongen_url}

        if pushd ${moongen_dir} > /dev/null; then
            # point to private libmoon repo
            sed -i -e "s|url = .*|url = https://github.com/perftool-incubator/libmoon.git|" .gitmodules

            # manually initialize the libmoon submodule so we can tweak it
            git submodule update --init

            # point to private repos for libmoon dependencies
            sed -i -e "s|url = https://github.com/emmericp/LuaJIT|url = https://github.com/perftool-incubator/LuaJIT.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/emmericp/dpdk|url = https://github.com/perftool-incubator/dpdk.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/emmericp/pciids|url = https://github.com/perftool-incubator/pciids.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/emmericp/ljsyscall|url = https://github.com/perftool-incubator/ljsyscall.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/emmericp/pflua|url = https://github.com/perftool-incubator/pflua.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/emmericp/turbo|url = https://github.com/perftool-incubator/turbo.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/google/highwayhash.git|url = https://github.com/perftool-incubator/highwayhash.git|" libmoon/.gitmodules
            sed -i -e "s|url = https://github.com/01org/tbb.git|url = https://github.com/perftool-incubator/oneTBB.git|" libmoon/.gitmodules

            # manually init libmoon submodules so we can hack dpdk
            pushd libmoon
            git submodule update --init
            popd

            sed -i -e "s|CONFIG_RTE_EAL_IGB_UIO=y|CONFIG_RTE_EAL_IGB_UIO=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_KNI_KMOD=y|CONFIG_RTE_KNI_KMOD=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_PMD_KNI=y|CONFIG_RTE_LIBRTE_PMD_KNI=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_VHOST=y|CONFIG_RTE_LIBRTE_VHOST=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_VHOST_NUMA=y|CONFIG_RTE_LIBRTE_VHOST_NUMA=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_PMD_VHOST=y|CONFIG_RTE_LIBRTE_PMD_VHOST=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_PMD_AF_PACKET=y|CONFIG_RTE_LIBRTE_PMD_AF_PACKET=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_PMD_TAP=y|CONFIG_RTE_LIBRTE_PMD_TAP=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_LIBRTE_AVP_PMD=y|CONFIG_RTE_LIBRTE_AVP_PMD=n|" libmoon/deps/dpdk/config/common_linuxapp
            sed -i -e "s|CONFIG_RTE_VIRTIO_USER=y|CONFIG_RTE_VIRTIO_USER=n|" libmoon/deps/dpdk/config/common_linuxapp

            # disable the auto device binding, we don't want that to happen
            head -n -5 libmoon/build.sh > libmoon/foo
            echo ")" >> libmoon/foo
            chmod +x libmoon/foo
            mv libmoon/build.sh libmoon/build.sh.bak
            mv libmoon/foo libmoon/build.sh

            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_ether' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_net' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_ring' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_mempool' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_kni' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_kvargs' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_hash' libmoon/CMakeLists.txt
            sed '/^INCLUDE_DIRECTORIES(/a ${CMAKE_CURRENT_SOURCE_DIR}/deps/dpdk/lib/librte_mbuf' libmoon/CMakeLists.txt

            # modify timestamper:measureLatency to only return a nil
            # latency when the packet is actually thought to be lost;
            # return -1 for other error cases; this allows lost
            # packets and error cases to be handled differently
            sed -i -e 's/return nil/return -1/' -e "/looks like our packet got lost/{n;s/return -1/return nil/}" libmoon/lua/timestamping.lua

            # build MoonGen
            if ! ./build.sh; then
                echo "ERROR: MoonGen build failed."
                exit 1
            fi

            popd > /dev/null
        else
            echo "ERROR: Could not find MoonGen directory"
            exit 1
        fi

        # install a custom moongen-latency.lua dependency
        if [ -d ${luaipc_dir} ]; then
            /bin/rm -Rf ${luaipc_dir}
        fi

        git clone ${luaipc_url}

        if pushd ${luaipc_dir} > /dev/null; then
            sed -i -e "s|\(LUA_INCDIR =\).*|\1 ${tg_dir}/${moongen_dir}/libmoon/deps/luajit/src|" Makefile

            if ! make; then
                echo "ERROR: Failed to build ${luaipc_dir}"
                exit 1
            fi

            make install
            cp ipc.so /opt/trafficgen/lua-luaipc

            if ! make install; then
                echo "ERROR: luaipc install failed."
                exit 1
            fi

            # /opt/trafficgen/lua-luaipc is hard coded here because
            # it is hard coded into the moongen-latency.lua script
            mkdir -pv /opt/trafficgen/lua-luaipc
            if ! cp ipc.so /opt/trafficgen/lua-luaipc; then
                echo "ERROR: Failed to copy ipc.so to /opt/trafficgen/lua-luaipc."
                exit 1
            fi

            popd > /dev/null
        else
            echo "ERROR: Failed to clone ${luaipc_url}"
            exit 1
        fi

        popd > /dev/null
    fi
else
    echo "ERROR: Could not find trafficgen directory!"
    exit 1
fi

exit 0
