defmodule RefElixir.SystemMetrics do
  use GenServer

  @poll_interval 2_000

  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  def get_metrics do
    GenServer.call(__MODULE__, :get_metrics)
  end

  @impl true
  def init(_opts) do
    state = %{
      metrics: %{},
      prev_cpu: nil,
      prev_net: nil,
      prev_time: nil
    }

    state = poll(state)
    schedule_poll()
    {:ok, state}
  end

  @impl true
  def handle_call(:get_metrics, _from, state) do
    {:reply, state.metrics, state}
  end

  @impl true
  def handle_info(:poll, state) do
    state = poll(state)
    Phoenix.PubSub.broadcast(RefElixir.PubSub, "system_metrics", {:metrics_updated, state.metrics})
    schedule_poll()
    {:noreply, state}
  end

  defp schedule_poll do
    Process.send_after(self(), :poll, @poll_interval)
  end

  defp poll(state) do
    now = System.monotonic_time(:millisecond)
    raw_cpu = read_raw_cpu()
    raw_net = read_raw_net()

    cpu = calculate_cpu(raw_cpu, state.prev_cpu)
    net = calculate_net_rates(raw_net, state.prev_net, now, state.prev_time)

    metrics = %{
      cpu: cpu,
      memory: read_memory(),
      load: read_load(),
      uptime: read_uptime(),
      temperatures: read_temperatures(),
      disks: read_disks(),
      network: net,
      hostname: read_hostname(),
      os_info: read_os_info(),
      kernel: read_kernel(),
      process_count: read_process_count(),
      time: DateTime.utc_now()
    }

    %{state | metrics: metrics, prev_cpu: raw_cpu, prev_net: raw_net, prev_time: now}
  end

  # --- CPU ---

  defp read_raw_cpu do
    case File.read("/proc/stat") do
      {:ok, content} ->
        content
        |> String.split("\n")
        |> Enum.filter(&String.starts_with?(&1, "cpu"))
        |> Enum.map(fn line ->
          [name | values] = String.split(line)
          nums = Enum.map(values, &String.to_integer/1)
          {name, nums}
        end)

      _ ->
        []
    end
  end

  defp calculate_cpu(current, nil), do: calculate_cpu(current, current)

  defp calculate_cpu(current, previous) do
    prev_map = Map.new(previous)

    Enum.map(current, fn {name, vals} ->
      prev_vals = Map.get(prev_map, name, vals)

      deltas = Enum.zip(vals, prev_vals) |> Enum.map(fn {a, b} -> a - b end)
      total = Enum.sum(deltas)
      idle = Enum.at(deltas, 3, 0) + Enum.at(deltas, 4, 0)

      usage =
        if total > 0,
          do: Float.round((total - idle) / total * 100, 1),
          else: 0.0

      %{name: name, usage: usage}
    end)
  end

  # --- Memory ---

  defp read_memory do
    case File.read("/proc/meminfo") do
      {:ok, content} ->
        parsed =
          content
          |> String.split("\n")
          |> Enum.reduce(%{}, fn line, acc ->
            case String.split(line, ~r/:\s+/) do
              [key, val] ->
                kb = val |> String.split() |> List.first() |> String.to_integer()
                Map.put(acc, key, kb)

              _ ->
                acc
            end
          end)

        total = Map.get(parsed, "MemTotal", 0)
        available = Map.get(parsed, "MemAvailable", 0)
        cached = Map.get(parsed, "Cached", 0) + Map.get(parsed, "Buffers", 0)
        used = total - available

        %{
          total_kb: total,
          used_kb: used,
          available_kb: available,
          cached_kb: cached,
          usage_pct: if(total > 0, do: Float.round(used / total * 100, 1), else: 0.0)
        }

      _ ->
        %{total_kb: 0, used_kb: 0, available_kb: 0, cached_kb: 0, usage_pct: 0.0}
    end
  end

  # --- Load ---

  defp read_load do
    case File.read("/proc/loadavg") do
      {:ok, content} ->
        parts = String.split(content)

        %{
          one: parts |> Enum.at(0, "0") |> String.to_float(),
          five: parts |> Enum.at(1, "0") |> String.to_float(),
          fifteen: parts |> Enum.at(2, "0") |> String.to_float()
        }

      _ ->
        %{one: 0.0, five: 0.0, fifteen: 0.0}
    end
  end

  # --- Uptime ---

  defp read_uptime do
    case File.read("/proc/uptime") do
      {:ok, content} ->
        secs = content |> String.split() |> List.first() |> String.to_float() |> trunc()
        days = div(secs, 86400)
        hours = div(rem(secs, 86400), 3600)
        minutes = div(rem(secs, 3600), 60)
        %{seconds: secs, days: days, hours: hours, minutes: minutes}

      _ ->
        %{seconds: 0, days: 0, hours: 0, minutes: 0}
    end
  end

  # --- Temperature ---

  defp read_temperatures do
    case File.ls("/sys/class/thermal") do
      {:ok, zones} ->
        zones
        |> Enum.filter(&String.starts_with?(&1, "thermal_zone"))
        |> Enum.sort()
        |> Enum.reduce([], fn zone, acc ->
          temp_path = "/sys/class/thermal/#{zone}/temp"
          type_path = "/sys/class/thermal/#{zone}/type"

          with {:ok, temp_str} <- File.read(temp_path),
               temp_c = temp_str |> String.trim() |> String.to_integer() |> Kernel./(1000) do
            type =
              case File.read(type_path) do
                {:ok, t} -> String.trim(t)
                _ -> zone
              end

            [%{zone: zone, type: type, temp_c: Float.round(temp_c / 1, 1)} | acc]
          else
            _ -> acc
          end
        end)
        |> Enum.reverse()

      _ ->
        []
    end
  end

  # --- Disk ---

  defp read_disks do
    case System.cmd("df", ["-h", "--output=target,size,used,avail,pcent"], stderr_to_stdout: true) do
      {output, 0} ->
        output
        |> String.split("\n")
        |> Enum.drop(1)
        |> Enum.reject(&(String.trim(&1) == ""))
        |> Enum.filter(fn line ->
          mount = line |> String.split() |> List.first("")
          mount in ["/", "/var", "/home", "/data"]
        end)
        |> Enum.map(fn line ->
          parts = String.split(line)

          %{
            mount: Enum.at(parts, 0, ""),
            size: Enum.at(parts, 1, "0"),
            used: Enum.at(parts, 2, "0"),
            avail: Enum.at(parts, 3, "0"),
            usage_pct: parts |> Enum.at(4, "0%") |> String.trim_trailing("%") |> parse_int()
          }
        end)

      _ ->
        []
    end
  end

  # --- Network ---

  defp read_raw_net do
    case File.read("/proc/net/dev") do
      {:ok, content} ->
        content
        |> String.split("\n")
        |> Enum.drop(2)
        |> Enum.reject(&(String.trim(&1) == ""))
        |> Enum.reduce(%{}, fn line, acc ->
          parts = String.split(line)
          iface = String.trim_trailing(List.first(parts, ""), ":")

          if iface != "lo" do
            rx_bytes = parts |> Enum.at(1, "0") |> String.to_integer()
            tx_bytes = parts |> Enum.at(9, "0") |> String.to_integer()
            Map.put(acc, iface, %{rx_bytes: rx_bytes, tx_bytes: tx_bytes})
          else
            acc
          end
        end)

      _ ->
        %{}
    end
  end

  defp calculate_net_rates(current, nil, _now, _prev_time) do
    Enum.map(current, fn {iface, stats} ->
      %{iface: iface, rx_bytes: stats.rx_bytes, tx_bytes: stats.tx_bytes, rx_rate: 0, tx_rate: 0}
    end)
  end

  defp calculate_net_rates(current, previous, now, prev_time) do
    elapsed_s = max((now - prev_time) / 1000, 0.001)

    Enum.map(current, fn {iface, stats} ->
      prev = Map.get(previous, iface, stats)
      rx_rate = trunc((stats.rx_bytes - prev.rx_bytes) / elapsed_s)
      tx_rate = trunc((stats.tx_bytes - prev.tx_bytes) / elapsed_s)

      %{
        iface: iface,
        rx_bytes: stats.rx_bytes,
        tx_bytes: stats.tx_bytes,
        rx_rate: max(rx_rate, 0),
        tx_rate: max(tx_rate, 0)
      }
    end)
  end

  # --- System Info ---

  defp read_hostname do
    case :inet.gethostname() do
      {:ok, name} -> to_string(name)
      _ -> "unknown"
    end
  end

  defp read_os_info do
    case File.read("/etc/os-release") do
      {:ok, content} ->
        parsed =
          content
          |> String.split("\n")
          |> Enum.reduce(%{}, fn line, acc ->
            case String.split(line, "=", parts: 2) do
              [key, val] -> Map.put(acc, key, String.trim(val, "\""))
              _ -> acc
            end
          end)

        %{
          name: Map.get(parsed, "PRETTY_NAME", Map.get(parsed, "NAME", "Linux")),
          version: Map.get(parsed, "VERSION_ID", "")
        }

      _ ->
        %{name: "Linux", version: ""}
    end
  end

  defp read_kernel do
    case File.read("/proc/version") do
      {:ok, content} ->
        content |> String.split() |> Enum.at(2, "unknown")

      _ ->
        "unknown"
    end
  end

  defp read_process_count do
    case File.ls("/proc") do
      {:ok, entries} ->
        Enum.count(entries, fn e -> match?({_, ""}, Integer.parse(e)) end)

      _ ->
        0
    end
  end

  defp parse_int(str) do
    case Integer.parse(str) do
      {n, _} -> n
      :error -> 0
    end
  end
end
