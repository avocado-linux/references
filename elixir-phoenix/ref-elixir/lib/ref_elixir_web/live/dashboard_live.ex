defmodule RefElixirWeb.DashboardLive do
  use RefElixirWeb, :live_view

  @impl true
  def mount(_params, _session, socket) do
    if connected?(socket) do
      Phoenix.PubSub.subscribe(RefElixir.PubSub, "system_metrics")
    end

    metrics = RefElixir.SystemMetrics.get_metrics()
    {:ok, assign(socket, metrics: metrics, page_title: "Dashboard")}
  end

  @impl true
  def handle_info({:metrics_updated, metrics}, socket) do
    {:noreply, assign(socket, metrics: metrics)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="min-h-screen bg-base-300 text-base-content p-4 flex flex-col gap-4">
      <%!-- Header --%>
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="text-2xl font-bold">{@metrics.hostname}</div>
          <div class="badge badge-primary badge-lg">{@metrics.os_info.name}</div>
        </div>
        <div class="flex items-center gap-4 text-sm opacity-70">
          <span>Kernel {@metrics.kernel}</span>
          <span>{format_uptime(@metrics.uptime)}</span>
          <span class="font-mono">{Calendar.strftime(@metrics.time, "%H:%M:%S UTC")}</span>
        </div>
      </div>

      <%!-- Main Grid --%>
      <div class="grid grid-cols-3 gap-4 flex-1">
        <%!-- CPU Card --%>
        <div class="card bg-base-100 shadow-lg">
          <div class="card-body p-4">
            <h2 class="card-title text-sm uppercase tracking-wider opacity-60">CPU</h2>
            <div class="flex flex-col gap-2 mt-2">
              <%= for core <- @metrics.cpu do %>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-mono w-10 opacity-60">{core.name}</span>
                  <div class="flex-1 bg-base-300 rounded-full h-5 overflow-hidden">
                    <div
                      class={"h-full rounded-full transition-all duration-500 " <> cpu_color(core.usage)}
                      style={"width: #{core.usage}%"}
                    />
                  </div>
                  <span class="text-xs font-mono w-12 text-right">{core.usage}%</span>
                </div>
              <% end %>
            </div>
            <div class="mt-2 text-xs opacity-60">
              Load: {@metrics.load.one} / {@metrics.load.five} / {@metrics.load.fifteen}
              &middot; {Integer.to_string(@metrics.process_count)} processes
            </div>
          </div>
        </div>

        <%!-- Memory Card --%>
        <div class="card bg-base-100 shadow-lg">
          <div class="card-body p-4">
            <h2 class="card-title text-sm uppercase tracking-wider opacity-60">Memory</h2>
            <div class="flex flex-col items-center justify-center flex-1 gap-3 mt-2">
              <div class={"radial-progress text-5xl " <> mem_color(@metrics.memory.usage_pct)}
                   style={"--value:#{@metrics.memory.usage_pct}; --size:10rem; --thickness:0.8rem;"}
                   role="progressbar">
                <span class="text-2xl font-bold">{@metrics.memory.usage_pct}%</span>
              </div>
              <div class="text-center space-y-1">
                <div class="text-sm">
                  {format_kb(@metrics.memory.used_kb)} / {format_kb(@metrics.memory.total_kb)}
                </div>
                <div class="text-xs opacity-60">
                  {format_kb(@metrics.memory.available_kb)} available
                  &middot; {format_kb(@metrics.memory.cached_kb)} cached
                </div>
              </div>
            </div>
          </div>
        </div>

        <%!-- Temperature & Disk Card --%>
        <div class="card bg-base-100 shadow-lg">
          <div class="card-body p-4">
            <h2 class="card-title text-sm uppercase tracking-wider opacity-60">Temperature</h2>
            <%= if @metrics.temperatures == [] do %>
              <div class="text-sm opacity-40 mt-2">No thermal zones detected</div>
            <% else %>
              <div class="flex flex-col gap-2 mt-2">
                <%= for tz <- @metrics.temperatures do %>
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-mono opacity-60">{tz.type}</span>
                    <span class={"text-lg font-bold " <> temp_color(tz.temp_c)}>
                      {tz.temp_c}&deg;C
                    </span>
                  </div>
                <% end %>
              </div>
            <% end %>

            <div class="divider my-1"></div>

            <h2 class="card-title text-sm uppercase tracking-wider opacity-60">Disk</h2>
            <div class="flex flex-col gap-2 mt-1">
              <%= for disk <- @metrics.disks do %>
                <div>
                  <div class="flex items-center justify-between text-xs mb-1">
                    <span class="font-mono opacity-60">{disk.mount}</span>
                    <span>{disk.used} / {disk.size}</span>
                  </div>
                  <div class="bg-base-300 rounded-full h-3 overflow-hidden">
                    <div
                      class={"h-full rounded-full transition-all duration-500 " <> disk_color(disk.usage_pct)}
                      style={"width: #{disk.usage_pct}%"}
                    />
                  </div>
                </div>
              <% end %>
            </div>
          </div>
        </div>
      </div>

      <%!-- Bottom Row: Network --%>
      <div class="card bg-base-100 shadow-lg">
        <div class="card-body p-4">
          <h2 class="card-title text-sm uppercase tracking-wider opacity-60">Network</h2>
          <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-2">
            <%= for iface <- @metrics.network do %>
              <div class="bg-base-200 rounded-lg p-3">
                <div class="font-mono font-bold text-sm mb-2">{iface.iface}</div>
                <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <div class="opacity-60">RX</div>
                  <div class="text-right font-mono">{format_bytes(iface.rx_bytes)}</div>
                  <div class="opacity-60">TX</div>
                  <div class="text-right font-mono">{format_bytes(iface.tx_bytes)}</div>
                  <div class="opacity-60">&darr;</div>
                  <div class="text-right font-mono text-info">{format_rate(iface.rx_rate)}</div>
                  <div class="opacity-60">&uarr;</div>
                  <div class="text-right font-mono text-success">{format_rate(iface.tx_rate)}</div>
                </div>
              </div>
            <% end %>
          </div>
        </div>
      </div>
    </div>
    """
  end

  # --- Formatting helpers ---

  defp format_uptime(%{days: d, hours: h, minutes: m}) do
    parts = []
    parts = if d > 0, do: parts ++ ["#{d}d"], else: parts
    parts = parts ++ ["#{h}h", "#{m}m"]
    "up " <> Enum.join(parts, " ")
  end

  defp format_kb(kb) when kb >= 1_048_576, do: "#{Float.round(kb / 1_048_576, 1)} GB"
  defp format_kb(kb) when kb >= 1024, do: "#{Float.round(kb / 1024, 1)} MB"
  defp format_kb(kb), do: "#{kb} KB"

  defp format_bytes(b) when b >= 1_073_741_824, do: "#{Float.round(b / 1_073_741_824, 1)} GB"
  defp format_bytes(b) when b >= 1_048_576, do: "#{Float.round(b / 1_048_576, 1)} MB"
  defp format_bytes(b) when b >= 1024, do: "#{Float.round(b / 1024, 1)} KB"
  defp format_bytes(b), do: "#{b} B"

  defp format_rate(bps) when bps >= 1_048_576, do: "#{Float.round(bps / 1_048_576, 1)} MB/s"
  defp format_rate(bps) when bps >= 1024, do: "#{Float.round(bps / 1024, 1)} KB/s"
  defp format_rate(bps), do: "#{bps} B/s"

  # --- Color helpers ---

  defp cpu_color(pct) when pct >= 90, do: "bg-error"
  defp cpu_color(pct) when pct >= 70, do: "bg-warning"
  defp cpu_color(_pct), do: "bg-primary"

  defp mem_color(pct) when pct >= 90, do: "text-error"
  defp mem_color(pct) when pct >= 70, do: "text-warning"
  defp mem_color(_pct), do: "text-primary"

  defp temp_color(c) when c >= 80, do: "text-error"
  defp temp_color(c) when c >= 65, do: "text-warning"
  defp temp_color(_c), do: "text-success"

  defp disk_color(pct) when pct >= 90, do: "bg-error"
  defp disk_color(pct) when pct >= 75, do: "bg-warning"
  defp disk_color(_pct), do: "bg-primary"
end
