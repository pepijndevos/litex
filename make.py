#!/usr/bin/env python3

import sys, os, argparse, importlib, subprocess, struct

from mibuild.tools import write_to_file
from migen.util.misc import autotype
from migen.fhdl import simplify

from misoclib.gensoc import cpuif
from misoclib.s6ddrphy import initsequence
import programmer

def _get_args():
	parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
		description="""\
MiSoC - a high performance and small footprint SoC based on Migen.

This program builds and/or loads MiSoC components.
One or several actions can be specified:

clean           delete previous build(s).
build-bitstream build FPGA bitstream. Implies build-bios on targets with
                integrated BIOS.
build-headers   build software header files with CSR/IRQ/SDRAM_PHY definitions.
build-csr-csv   save CSR map into CSV file.
build-bios      build BIOS. Implies build-header.

load-bitstream  load bitstream into volatile storage.
flash-bitstream load bitstream into non-volatile storage.
flash-bios      load BIOS into non-volatile storage.

all             clean, build-bitstream, build-bios, flash-bitstream, flash-bios.

Load/flash actions use the existing outputs, and do not trigger new builds.
""")

	parser.add_argument("-t", "--target", default="mlabs_video", help="SoC type to build")
	parser.add_argument("-s", "--sub-target", default="", help="variant of the SoC type to build")
	parser.add_argument("-p", "--platform", default=None, help="platform to build for")
	parser.add_argument("-Ot", "--target-option", default=[], nargs=2, action="append", help="set target-specific option")
	parser.add_argument("-X", "--external", default="", help="use external directory for targets, platforms and imports")

	parser.add_argument("-d", "--decorate", default=[], action="append", help="apply simplification decorator to top-level")
	parser.add_argument("-Ob", "--build-option", default=[], nargs=2, action="append", help="set build option")
	parser.add_argument("-f", "--flash-proxy-dir", default=None, help="set search directory for flash proxy bitstreams")

	parser.add_argument("action", nargs="+", help="specify an action")

	return parser.parse_args()

def _misoc_import(default, external, name):
	if external:
		try:
			del sys.modules[name] # force external path search
		except KeyError:
			pass
		loader = importlib.find_loader(name, [external])
		if loader is None:
			# try internal import
			return importlib.import_module(default + "." + name)
		return loader.load_module()
	else:
		return importlib.import_module(default + "." + name)

if __name__ == "__main__":
	args = _get_args()

	external_target = ""
	external_platform = ""
	if args.external:
		external_target = os.path.join(args.external, "targets")
		external_platform = os.path.join(args.external, "platforms")
		sys.path.insert(1, os.path.abspath(args.external))

	# create top-level SoC object
	target_module = _misoc_import("targets", external_target, args.target)
	if args.sub_target:
		top_class = getattr(target_module, args.sub_target)
	else:
		top_class = target_module.default_subtarget

	if args.platform is None:
		platform_name = top_class.default_platform
	else:
		platform_name = args.platform
	platform_module = _misoc_import("mibuild.platforms", external_platform, platform_name)
	platform = platform_module.Platform()

	build_name = top_class.__name__.lower() + "-" + platform_name
	top_kwargs = dict((k, autotype(v)) for k, v in args.target_option)
	soc = top_class(platform, **top_kwargs)
	soc.finalize()

	# decode actions
	action_list = ["clean", "build-bitstream", "build-headers", "build-csr-csv", "build-bios",
		"load-bitstream", "flash-bitstream", "flash-bios", "all"]
	actions = {k: False for k in action_list}
	for action in args.action:
		if action in actions:
			actions[action] = True
		else:
			print("Unknown action: "+action+". Valid actions are:")
			for a in action_list:
				print("  "+a)
			sys.exit(1)

	print("""\
                __  ___  _   ____     _____
               /  |/  / (_) / __/__  / ___/
              / /|_/ / / / _\ \/ _ \/ /__
             /_/  /_/ /_/ /___/\___/\___/

a high performance and small footprint SoC based on Migen

====== Building for: ======
Platform:  {}
Target:    {}
Subtarget: {}
===========================""".format(platform_name, args.target, top_class.__name__))

	# dependencies
	if actions["all"]:
		actions["clean"] = True
		actions["build-bitstream"] = True
		actions["build-bios"] = True
		actions["flash-bitstream"] = True
		actions["flash-bios"] = True
	if actions["build-bitstream"] and hasattr(soc, "init_bios_memory"):
		actions["build-bios"] = True
	if actions["build-bios"]:
		actions["build-headers"] = True

	if actions["clean"]:
		subprocess.call(["rm", "-rf", "build/*"])

	if actions["build-headers"]:
		boilerplate = """/*
 * Platform:  {}
 * Target:    {}
 * Subtarget: {}
 */

""".format(platform_name, args.target, top_class.__name__)
		linker_header = cpuif.get_linker_regions(soc.cpu_memory_regions)
		write_to_file("software/include/generated/regions.ld", boilerplate + linker_header)
		try:
			flash_boot_address = soc.flash_boot_address
		except AttributeError:
			flash_boot_address = None
		mem_header = cpuif.get_mem_header(soc.cpu_memory_regions, flash_boot_address)
		write_to_file("software/include/generated/mem.h", boilerplate + mem_header)
		csr_header = cpuif.get_csr_header(soc.csr_base, soc.csrbankarray, soc.interrupt_map)
		write_to_file("software/include/generated/csr.h", boilerplate + csr_header)
		if hasattr(soc, "ddrphy"):
			sdram_phy_header = initsequence.get_sdram_phy_header(soc.ddrphy)
			write_to_file("software/include/generated/sdram_phy.h", boilerplate + sdram_phy_header)

	if actions["build-csr-csv"]:
		csr_csv = cpuif.get_csr_csv(soc.csr_base, soc.csrbankarray)
		write_to_file(args.csr_csv, csr_csv)

	if actions["build-bios"]:
		ret = subprocess.call(["make", "-C", "software/bios"])
		if ret:
			raise OSError("BIOS build failed")

	if hasattr(soc, "init_bios_memory"):
		with open("software/bios/bios.bin", "rb") as bios_file:
			bios_data = []
			while True:
				w = bios_file.read(4)
				if not w:
					break
				bios_data.append(struct.unpack(">I", w)[0])
		soc.init_bios_memory(bios_data)

	if actions["build-bitstream"]:
		for decorator in args.decorate:
			soc = getattr(simplify, decorator)(soc)
		build_kwargs = dict((k, autotype(v)) for k, v in args.build_option)
		platform.build(soc, build_name=build_name, **build_kwargs)

	if actions["load-bitstream"] or actions["flash-bitstream"] or actions["flash-bios"]:
		prog = programmer.create_programmer(platform.name, args.flash_proxy_dir)
		if actions["load-bitstream"]:
			prog.load_bitstream("build/" + build_name + platform.bitstream_ext)
		if actions["flash-bitstream"]:
			if prog.needs_bitreverse:
				flashbit = "build/" + build_name + ".fpg"
				subprocess.call(["tools/byteswap",
					"build/" + build_name + ".bin",
					flashbit])
			else:
				flashbit = "build/" + build_name + ".bin"
			prog.flash(0, flashbit)
		if actions["flash-bios"]:
			prog.flash(soc.cpu_reset_address, "software/bios/bios.bin")
