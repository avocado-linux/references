# rb3gen2 core layout

Copied verbatim from `cpus/rubikpi3`, because the RB3 Gen 2 Vision Kit and the
RUBIK Pi 3 are the same SoC: QCS6490, one Kryo cluster of 8 cores in the same
4x A78 / 4x A55 arrangement. The isolation choice is a property of the silicon,
not of the board, so the pinning that was measured on the RubikPi applies here
unchanged.

That is an assumption worth re-testing rather than trusting: rerun the demo and
compare `rtt p50` against the RubikPi numbers before treating these values as
measured on THIS board. If they differ materially, the layout here is what to
change -- adding a board is adding a directory under cpus/, nothing else.

## What upstream does differently

meta-qcom's `rb3gen2-core-kit.conf` isolates for RT with these, folded into the
kernel cmdline by `qcom-common.inc`:

    QCOM_RT_CPU=7  QCOM_IRQAFF=0-6  QCOM_RCU_NOCBS=7
    QCOM_RCU_EXPEDITED=1  QCOM_CPUIDLE_OFF=1

That is the opposite assignment to the one here: upstream reserves the prime
core (7) for a single RT task and gives 0-6 to housekeeping, while this layout
puts the VMs on 4-6 and leaves 0-3,7 for housekeeping. Ours is not wrong --
upstream is isolating ONE core for ONE RT thread, and a two-VM ping-pong needs
two big cores that share L3 -- and the split here is the one that was actually
measured. Do not "fix" it to match upstream.

The part worth stealing is the rest of the list, which has no equivalent here.
`AllowedCPUs`/`CPUAffinity` are cgroup placement only: they do not keep
interrupts off the VM cores and do not stop those cores entering deep idle,
and a wakeup from a deep C-state costs microseconds -- squarely in the range
this demo measures. So `irqaffinity` and `cpuidle.off=1` are real headroom on
tail latency (not on p50, which the ping-pong keeps warm anyway).

Both are reachable at runtime, which is the cheap way to test the idea before
touching any machine conf:

    # keep IRQs off the VM cores
    for i in /proc/irq/[0-9]*; do echo f > $i/smp_affinity 2>/dev/null; done
    # forbid deep idle on 4-6
    for c in 4 5 6; do
      for s in /sys/devices/system/cpu/cpu$c/cpuidle/state[1-9]; do
        echo 1 > $s/disable; done; done

Measure with and without before deciding whether this belongs in the BSP. It
is deliberately NOT in the machine conf: `cpuidle.off=1` is machine-wide and
costs power and thermal headroom for every non-RT user of the board.
