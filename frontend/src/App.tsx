import { useEffect, useState } from "react";
import {
  Activity,
  Aperture,
  BarChart3,
  BookOpen,
  Boxes,
  History,
  Images,
  LayoutGrid,
  ListTodo,
  Moon,
  Settings2,
  Sparkles,
  Sun,
  Wifi,
} from "lucide-react";
import { ROUTES, useHashRoute } from "./lib/hooks";
import { useStore } from "./lib/store";
import { api } from "./lib/api";
import { Button, IconButton, ToastHost } from "./components/ui";
import TaskCenter from "./components/TaskCenter";
import Studio from "./pages/Studio";
import Models from "./pages/Models";
import Library from "./pages/Library";
import Gallery from "./pages/Gallery";
import Records from "./pages/Records";
import Insights from "./pages/Insights";
import SettingsPage from "./pages/Settings";

const ICONS: Record<string, typeof Sparkles> = {
  studio: Sparkles,
  models: Boxes,
  library: Images,
  gallery: LayoutGrid,
  records: History,
  insights: BarChart3,
  settings: Settings2,
};

export default function App() {
  const [route, navigate] = useHashRoute();
  const { loading, error, models, channels, refresh, resolvedTheme, setTheme } = useStore();
  const [active, setActive] = useState(0);
  const [taskOpen, setTaskOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await api.jobs.list({ status: "active", limit: 50 });
        if (alive) setActive(data.total);
      } catch {
        /* offline */
      }
    };
    void tick();
    const timer = window.setInterval(tick, 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const meta = ROUTES.find((item) => item.id === route) ?? ROUTES[0];
  const realChannels = channels.filter((channel) => channel.protocol !== "mock").length;

  return (
    <div className="app">
      <aside className="rail">
        <button className="brand" onClick={() => navigate("studio")} title="一格 OneFrame">
          <span className="brand-mark">
            <svg viewBox="0 0 28 28" aria-hidden="true">
              <rect x="3.5" y="3.5" width="21" height="21" rx="6" />
              <rect x="10" y="10" width="8" height="8" rx="2.4" />
              <circle cx="21.4" cy="6.6" r="1.5" />
            </svg>
          </span>
          <span className="brand-text">
            <strong>一格</strong>
            <em>ONEFRAME</em>
          </span>
        </button>

        <nav className="rail-nav">
          {ROUTES.map((item) => {
            const Icon = ICONS[item.id];
            return (
              <button
                key={item.id}
                className={`rail-item ${route === item.id ? "is-active" : ""}`}
                onClick={() => navigate(item.id)}
                aria-current={route === item.id}
              >
                <Icon size={20} strokeWidth={1.7} />
                <span>{item.label}</span>
                {item.id === "studio" && active > 0 && <i className="rail-badge">{active}</i>}
              </button>
            );
          })}
        </nav>

        <div className="rail-foot">
          <a className="rail-link" href="/docs" target="_blank" rel="noreferrer" title="FastAPI 接口文档">
            <BookOpen size={17} strokeWidth={1.7} />
          </a>
          <span className="rail-status" title={realChannels ? `${realChannels} 个已接入服务` : "仅离线演示"}>
            <Wifi size={16} strokeWidth={1.7} />
            <i className={realChannels ? "is-ok" : ""} />
          </span>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="crumbs">
            <span>一格</span>
            <i>/</i>
            <strong>{meta.label}</strong>
            <em>{meta.hint}</em>
          </div>
          <div className="top-actions">
            {active > 0 && (
              <span className="live-pill">
                <Activity size={14} />
                {active} 个任务进行中
              </span>
            )}
            <IconButton
              label={resolvedTheme === "light" ? "切换到深色" : "切换到浅色"}
              onClick={() => setTheme(resolvedTheme === "light" ? "dark" : "light")}
            >
              {resolvedTheme === "light" ? <Moon size={16} /> : <Sun size={16} />}
            </IconButton>
            <Button
              variant="ghost"
              size="sm"
              icon={<ListTodo size={15} />}
              onClick={() => setTaskOpen(true)}
            >
              任务{active > 0 ? ` · ${active}` : ""}
            </Button>
            <span className="model-pill" title="已接入的创作模型">
              <Aperture size={14} />
              {models.filter((model) => model.available).length} / {models.length} 模型可用
            </span>
            <Button variant="primary" size="sm" icon={<Sparkles size={15} />} onClick={() => navigate("studio")}>
              开始创作
            </Button>
          </div>
        </header>

        <main className="page">
          {loading && (
            <div className="boot">
              <span className="spinner" />
              <p>正在唤醒本地工作台…</p>
            </div>
          )}
          {!loading && error && (
            <div className="boot boot-error">
              <h2>连接不上本地服务</h2>
              <p>{error}</p>
              <Button variant="primary" onClick={() => void refresh()}>
                重试
              </Button>
            </div>
          )}
          {!loading && !error && (
            <>
              {route === "studio" && <Studio onGoModels={() => navigate("models")} />}
              {route === "models" && <Models />}
              {route === "library" && <Library onUse={() => navigate("studio")} />}
              {route === "gallery" && <Gallery />}
              {route === "records" && <Records />}
              {route === "insights" && <Insights />}
              {route === "settings" && <SettingsPage />}
            </>
          )}
        </main>
      </div>
      <TaskCenter open={taskOpen} onClose={() => setTaskOpen(false)} />
      <ToastHost />
    </div>
  );
}
