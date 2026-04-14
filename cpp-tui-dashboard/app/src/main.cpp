#include <ftxui/component/component.hpp>
#include <ftxui/component/event.hpp>
#include <ftxui/component/screen_interactive.hpp>
#include <ftxui/dom/elements.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <deque>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <unistd.h>
#include <vector>

using namespace ftxui;

struct JournalEntry {
    int priority = 6;
    std::string unit;
    std::string message;
};

struct Dashboard {
    std::mutex mtx;
    std::array<int, 8> severity_counts{};
    std::map<std::string, int> unit_counts;
    std::deque<JournalEntry> recent;
    std::deque<float> rate_history;
    int msgs_this_sec = 0;
    float current_rate = 0;
    int total = 0;

    static constexpr size_t kMaxRecent = 100;
    static constexpr size_t kMaxHistory = 60;
};

static const char* priority_label(int p) {
    constexpr const char* labels[] = {
        "EMERG", "ALERT", "CRIT", "ERR", "WARN", "NOTICE", "INFO", "DEBUG",
    };
    return (p >= 0 && p <= 7) ? labels[p] : "???";
}

static Color priority_color(int p) {
    switch (p) {
        case 0: case 1: case 2: return Color::RedLight;
        case 3:                  return Color::Red;
        case 4:                  return Color::Yellow;
        case 5:                  return Color::Cyan;
        case 6:                  return Color::Green;
        case 7:                  return Color::GrayDark;
        default:                 return Color::White;
    }
}

static void journal_reader(Dashboard& db, std::atomic<bool>& running) {
    FILE* pipe = popen("journalctl -f -o export --no-pager -n 50 2>/dev/null", "r");
    if (!pipe) return;

    char buf[4096];
    JournalEntry entry;
    bool has_data = false;

    while (running.load() && fgets(buf, sizeof(buf), pipe)) {
        std::string line(buf);
        if (!line.empty() && line.back() == '\n') line.pop_back();

        if (line.empty()) {
            if (has_data) {
                std::lock_guard<std::mutex> lock(db.mtx);
                if (entry.priority >= 0 && entry.priority <= 7)
                    db.severity_counts[entry.priority]++;
                if (!entry.unit.empty())
                    db.unit_counts[entry.unit]++;
                db.total++;
                db.msgs_this_sec++;
                db.recent.push_front(entry);
                if (db.recent.size() > Dashboard::kMaxRecent)
                    db.recent.pop_back();
            }
            entry = {};
            has_data = false;
            continue;
        }

        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        has_data = true;

        std::string key = line.substr(0, eq);
        std::string val = line.substr(eq + 1);

        if (key == "PRIORITY" && !val.empty())
            entry.priority = val[0] - '0';
        else if ((key == "_SYSTEMD_UNIT" || key == "SYSLOG_IDENTIFIER") && entry.unit.empty())
            entry.unit = val;
        else if (key == "MESSAGE")
            entry.message = val;
    }

    pclose(pipe);
}

static void rate_ticker(Dashboard& db, std::atomic<bool>& running) {
    while (running.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        std::lock_guard<std::mutex> lock(db.mtx);
        db.current_rate = static_cast<float>(db.msgs_this_sec);
        db.rate_history.push_back(db.current_rate);
        if (db.rate_history.size() > Dashboard::kMaxHistory)
            db.rate_history.pop_front();
        db.msgs_this_sec = 0;
    }
}

static void run_tui(Dashboard& db, std::atomic<bool>& running) {
    auto screen = ScreenInteractive::Fullscreen();

    auto renderer = Renderer([&] {
        std::lock_guard<std::mutex> lock(db.mtx);

        // --- sparkline ---
        const char* blocks[] = {" ", "\u2581", "\u2582", "\u2583",
                                "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"};
        float max_rate = 1.0f;
        for (auto r : db.rate_history)
            max_rate = std::max(max_rate, r);

        std::string spark;
        size_t pad = Dashboard::kMaxHistory - db.rate_history.size();
        for (size_t i = 0; i < pad; i++) spark += " ";
        for (auto r : db.rate_history)
            spark += blocks[std::clamp(int(r / max_rate * 8), 0, 8)];

        // --- severity panel ---
        Elements sev_rows;
        for (int i = 0; i <= 7; i++) {
            if (db.severity_counts[i] == 0) continue;
            sev_rows.push_back(hbox({
                text(priority_label(i)) | color(priority_color(i))
                                        | size(WIDTH, EQUAL, 8),
                text(std::to_string(db.severity_counts[i])) | bold,
            }));
        }
        if (sev_rows.empty())
            sev_rows.push_back(text("(waiting...)") | dim);

        // --- top units panel ---
        std::vector<std::pair<int, std::string>> sorted_units;
        for (auto& [u, c] : db.unit_counts) sorted_units.push_back({c, u});
        std::sort(sorted_units.rbegin(), sorted_units.rend());

        Elements unit_rows;
        for (size_t i = 0; i < std::min(sorted_units.size(), size_t(8)); i++) {
            auto& [cnt, name] = sorted_units[i];
            std::string display = name.size() > 28 ? name.substr(0, 28) + "\u2026" : name;
            unit_rows.push_back(hbox({
                text(display) | size(WIDTH, EQUAL, 30),
                text(std::to_string(cnt)) | bold | align_right,
            }));
        }
        if (unit_rows.empty())
            unit_rows.push_back(text("(waiting...)") | dim);

        // --- recent messages ---
        Elements msg_rows;
        for (auto& e : db.recent) {
            std::string msg = e.message.size() > 100
                                  ? e.message.substr(0, 100) + "\u2026"
                                  : e.message;
            std::string unit = e.unit.empty() ? "???" : e.unit;
            if (unit.size() > 20) unit = unit.substr(0, 20);

            msg_rows.push_back(hbox({
                text("[") | dim,
                text(priority_label(e.priority)) | color(priority_color(e.priority)),
                text("] ") | dim,
                text(unit) | bold | size(WIDTH, EQUAL, 20),
                text(" "),
                text(msg),
            }));
        }
        if (msg_rows.empty())
            msg_rows.push_back(text("(waiting for journal entries...)") | dim);

        return vbox({
            hbox({
                text(" syslog-dashboard ") | bold | color(Color::Cyan),
                filler(),
                text(std::to_string(db.total) + " total ") | dim,
            }),
            separator(),
            hbox({
                text(" msg/s ") | dim,
                text(spark) | flex,
                text(" " + std::to_string(int(db.current_rate)) + "/s ") | bold,
            }),
            separator(),
            hbox({
                vbox(sev_rows) | border | size(WIDTH, EQUAL, 22),
                vbox(unit_rows) | border | flex,
            }),
            separator(),
            vbox(msg_rows) | flex | border,
            hbox({text(" q: quit ") | dim}),
        }) | border;
    });

    auto component = CatchEvent(renderer, [&](Event event) {
        if (event == Event::Character('q') || event == Event::Escape) {
            running.store(false);
            screen.Exit();
            return true;
        }
        return false;
    });

    std::thread refresher([&] {
        while (running.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
            screen.PostEvent(Event::Custom);
        }
    });

    screen.Loop(component);
    running.store(false);
    if (refresher.joinable()) refresher.join();
}

static void run_headless(Dashboard& db, std::atomic<bool>& running) {
    while (running.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(5));
        std::lock_guard<std::mutex> lock(db.mtx);
        std::printf("syslog-dashboard: %d total | %.0f msg/s | ERR:%d WARN:%d INFO:%d\n",
                    db.total, db.current_rate,
                    db.severity_counts[3], db.severity_counts[4], db.severity_counts[6]);
        std::fflush(stdout);
    }
}

int main() {
    Dashboard db;
    std::atomic<bool> running{true};

    std::thread reader(journal_reader, std::ref(db), std::ref(running));
    std::thread ticker(rate_ticker, std::ref(db), std::ref(running));

    if (isatty(STDOUT_FILENO))
        run_tui(db, running);
    else
        run_headless(db, running);

    running.store(false);
    if (reader.joinable()) reader.join();
    if (ticker.joinable()) ticker.join();
    return 0;
}
