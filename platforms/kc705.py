from mibuild.generic_platform import *
from mibuild.crg import SimpleCRG
from mibuild.xilinx_common import CRG_DS
from mibuild.xilinx_ise import XilinxISEPlatform
from mibuild.xilinx_vivado import XilinxVivadoPlatform
from mibuild.programmer import *

def _run_vivado(cmds):
	with subprocess.Popen("vivado -mode tcl", stdin=subprocess.PIPE, shell=True) as process:
		process.stdin.write(cmds.encode("ASCII"))
		process.communicate()

class VivadoProgrammer(Programmer):
	needs_bitreverse = False

	def load_bitstream(self, bitstream_file):
		cmds = """open_hw
connect_hw_server
open_hw_target [lindex [get_hw_targets -of_objects [get_hw_servers localhost]] 0]

set_property PROBES.FILE {{}} [lindex [get_hw_devices] 0]
set_property PROGRAM.FILE {{{bitstream}}} [lindex [get_hw_devices] 0]

program_hw_devices [lindex [get_hw_devices] 0]
refresh_hw_device [lindex [get_hw_devices] 0]

quit
""".format(bitstream=bitstream_file)
		_run_vivado(cmds)

	def flash(self, address, data_file):
		raise NotImplementedError

_io = [
	("user_led", 0, Pins("AB8"), IOStandard("LVCMOS15")),
	("user_led", 1, Pins("AA8"), IOStandard("LVCMOS15")),
	("user_led", 2, Pins("AC9"), IOStandard("LVCMOS15")),
	("user_led", 3, Pins("AB9"), IOStandard("LVCMOS15")),
	("user_led", 4, Pins("AE26"), IOStandard("LVCMOS25")),
	("user_led", 5, Pins("G19"), IOStandard("LVCMOS25")),
	("user_led", 6, Pins("E18"), IOStandard("LVCMOS25")),
	("user_led", 7, Pins("F16"), IOStandard("LVCMOS25")),

	("cpu_reset", 0, Pins("AB7"), IOStandard("LVCMOS15")),

	("clk200", 0,
		Subsignal("p", Pins("AD12"), IOStandard("LVDS")),
		Subsignal("n", Pins("AD11"), IOStandard("LVDS"))
	),

	("clk156", 0,
		Subsignal("p", Pins("K28"), IOStandard("LVDS_25")),
		Subsignal("n", Pins("K29"), IOStandard("LVDS_25"))
	),


	("serial", 0,
		Subsignal("cts", Pins("L27")),
		Subsignal("rts", Pins("K23")),
		Subsignal("tx", Pins("K24")),
		Subsignal("rx", Pins("M19")),
		IOStandard("LVCMOS25")
	),

	("eth_clocks", 0,
		Subsignal("tx", Pins("M28")),
		Subsignal("gtx", Pins("K30")),
		Subsignal("rx", Pins("U27")),
		IOStandard("LVCMOS25")
	),
	("eth", 0,
		Subsignal("rst_n", Pins("L20")),
		Subsignal("int_n", Pins("N30")),
		Subsignal("mdio", Pins("J21")),
		Subsignal("mdc", Pins("R23")),
		Subsignal("dv", Pins("R28")),
		Subsignal("rx_er", Pins("V26")),
		Subsignal("rx_data", Pins("U30 U25 T25 U28 R19 T27 T26 T28")),
		Subsignal("tx_en", Pins("M27")),
		Subsignal("tx_er", Pins("N29")),
		Subsignal("tx_data", Pins("N27 N25 M29 L28 J26 K26 L30 J28")),
		Subsignal("col", Pins("W19")),
		Subsignal("crs", Pins("R30")),
		IOStandard("LVCMOS25")
	),

]

def Platform(*args, toolchain="vivado", programmer="xc3sprog", **kwargs):
	if toolchain == "ise":
		xilinx_platform = XilinxISEPlatform
	elif toolchain == "vivado":
		xilinx_platform = XilinxVivadoPlatform
	else:
		raise ValueError

	class RealPlatform(xilinx_platform):
		bitgen_opt = "-g LCK_cycle:6 -g Binary:Yes -w -g ConfigRate:12 -g SPI_buswidth:4"

		def __init__(self, crg_factory=lambda p: CRG_DS(p, "clk200", "cpu_reset")):
			xilinx_platform.__init__(self, "xc7k325t-ffg900-2", _io, crg_factory)

		def create_programmer(self):
			if programmer == "xc3sprog":
				return XC3SProg("jtaghs1_fast", "bscan_spi_kc705.bit")
			elif programmer == "vivado":
				return VivadoProgrammer()
			else:
				raise ValueError

		def do_finalize(self, fragment):
			try:
				self.add_period_constraint(self.lookup_request("clk156").p, 6.4)
			except ConstraintError:
				pass
			try:
				self.add_period_constraint(self.lookup_request("clk200").p, 5.0)
			except ConstraintError:
				pass
			try:
				self.add_period_constraint(self.lookup_request("eth_clocks").rx, 8.0)
			except ConstraintError:
				pass
	return RealPlatform(*args, **kwargs)
