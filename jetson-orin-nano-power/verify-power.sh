#!/bin/sh
# Reads VDD_IN from the Orin Nano's INA3221 power monitor and reports mean and maximum power over a window, with the
# governors and power mode in force. Run it on the device, for example:
#   ssh root@<device> sh -s < verify-power.sh
# SETTLE is the uptime in seconds to wait for before sampling (default 240), WINDOW the sampling time (default 90).
set -eu

SETTLE=${SETTLE:-240}
WINDOW=${WINDOW:-90}
GPU=/sys/class/devfreq/17000000.gpu

hwmon=""
for h in /sys/class/hwmon/hwmon*; do
  [ "$(cat "$h/name" 2>/dev/null)" = ina3221 ] && hwmon=$h
done
[ -n "$hwmon" ] || { echo "no ina3221 hwmon device found" >&2; exit 1; }

while [ "$(cut -d. -f1 /proc/uptime)" -lt "$SETTLE" ]; do sleep 5; done

n=0
sum=0
max=0
end=$(( $(date +%s) + WINDOW ))
while [ "$(date +%s)" -lt "$end" ]; do
  mv=$(cat "$hwmon/in1_input")
  ma=$(cat "$hwmon/curr1_input")
  mw=$(( mv * ma / 1000 ))
  sum=$(( sum + mw ))
  n=$(( n + 1 ))
  [ "$mw" -gt "$max" ] && max=$mw
  sleep 1
done

echo "idle VDD_IN: mean=$(( sum / n )) mW max=$max mW (n=$n)"
echo "power mode: $(nvpmodel -q 2>&1 | tr '\n' ' ')"
echo "gpu: $(cat "$GPU/governor") at $(cat "$GPU/cur_freq") Hz"
echo "cpu0: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor) at $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq) kHz"
