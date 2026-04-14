defmodule RefElixir.Application do
  # See https://hexdocs.pm/elixir/Application.html
  # for more information on OTP Applications
  @moduledoc false

  use Application

  @impl true
  def start(_type, _args) do
    children = [
      RefElixirWeb.Telemetry,
      {DNSCluster, query: Application.get_env(:ref_elixir, :dns_cluster_query) || :ignore},
      {Phoenix.PubSub, name: RefElixir.PubSub},
      # System metrics collector
      RefElixir.SystemMetrics,
      # Start to serve requests, typically the last entry
      RefElixirWeb.Endpoint
    ]

    # See https://hexdocs.pm/elixir/Supervisor.html
    # for other strategies and supported options
    opts = [strategy: :one_for_one, name: RefElixir.Supervisor]
    Supervisor.start_link(children, opts)
  end

  # Tell Phoenix to update the endpoint configuration
  # whenever the application is updated.
  @impl true
  def config_change(changed, _new, removed) do
    RefElixirWeb.Endpoint.config_change(changed, removed)
    :ok
  end
end
