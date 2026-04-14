defmodule RefElixirWeb.PageController do
  use RefElixirWeb, :controller

  def home(conn, _params) do
    render(conn, :home)
  end
end
