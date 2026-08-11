import { useTranslation } from "react-i18next";
import { NavLink, Route, Routes } from "react-router-dom";
import { SUPPORTED_LOCALES } from "./i18n";
import Collection from "./pages/Collection";
import CollectionImport from "./pages/CollectionImport";
import Comparisons from "./pages/Comparisons";
import Dashboard from "./pages/Dashboard";
import Discover from "./pages/Discover";
import EdhrecDecks from "./pages/EdhrecDecks";
import ListDetail from "./pages/ListDetail";
import Lists from "./pages/Lists";
import ListsImport from "./pages/ListsImport";
import Prices from "./pages/Prices";
import Settings from "./pages/Settings";
import Sources from "./pages/Sources";
import SystemStatus from "./pages/SystemStatus";

const NAV_ITEMS: Array<{ to: string; key: string }> = [
  { to: "/", key: "nav.dashboard" },
  { to: "/collection", key: "nav.collection" },
  { to: "/collection/import", key: "nav.collectionImport" },
  { to: "/lists", key: "nav.lists" },
  { to: "/lists/import", key: "nav.listsImport" },
  { to: "/discover", key: "nav.discover" },
  { to: "/edhrec", key: "nav.edhrec" },
  { to: "/comparisons", key: "nav.comparisons" },
  { to: "/sources", key: "nav.sources" },
  { to: "/prices", key: "nav.prices" },
  { to: "/settings", key: "nav.settings" },
  { to: "/status", key: "nav.systemStatus" },
];

export default function App() {
  const { t, i18n } = useTranslation();

  return (
    <div className="cf-app">
      <aside className="cf-sidebar">
        <h1>{t("app.name")}</h1>
        <div className="cf-subtitle">{t("app.tagline")}</div>
        <nav className="cf-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              {t(item.key)}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="cf-main">
        <div className="cf-topbar">
          <select
            className="cf-lang-select"
            value={i18n.resolvedLanguage}
            onChange={(e) => i18n.changeLanguage(e.target.value)}
          >
            {SUPPORTED_LOCALES.map((loc) => (
              <option key={loc.code} value={loc.code}>
                {loc.label}
              </option>
            ))}
          </select>
        </div>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/collection" element={<Collection />} />
          <Route path="/collection/import" element={<CollectionImport />} />
          <Route path="/lists" element={<Lists />} />
          <Route path="/lists/import" element={<ListsImport />} />
          <Route path="/lists/:id" element={<ListDetail />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/edhrec" element={<EdhrecDecks />} />
          <Route path="/comparisons" element={<Comparisons />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/prices" element={<Prices />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/status" element={<SystemStatus />} />
        </Routes>
      </main>
    </div>
  );
}
