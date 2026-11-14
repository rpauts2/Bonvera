import { Suspense, lazy, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { SessionProvider, useSession } from "./state/session";
import { TabBar } from "./components/TabBar";
import { AcceptGate, BootScreen, ErrorScreen } from "./components/Gates";
import { BackButtonSync } from "./components/BackButtonSync";

const Home = lazy(() => import("./pages/Home"));
const Tasks = lazy(() => import("./pages/Tasks"));
const Catalog = lazy(() => import("./pages/Catalog"));
const Friends = lazy(() => import("./pages/Friends"));
const Profile = lazy(() => import("./pages/Profile"));
const Wallet = lazy(() => import("./pages/Wallet"));
const OfferPage = lazy(() => import("./pages/OfferPage"));
const MyApps = lazy(() => import("./pages/MyApps"));
const AppDetail = lazy(() => import("./pages/AppDetail"));
const History = lazy(() => import("./pages/History"));
const Withdraw = lazy(() => import("./pages/Withdraw"));
const Achievements = lazy(() => import("./pages/Achievements"));
const Leaderboard = lazy(() => import("./pages/Leaderboard"));
const Settings = lazy(() => import("./pages/Settings"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Support = lazy(() => import("./pages/Support"));
const Rules = lazy(() => import("./pages/Rules"));

const TAB_PATHS = ["/", "/tasks", "/catalog", "/friends", "/profile"];

function Shell() {
  const { user, ready, error } = useSession();
  const location = useLocation();
  const showTabs = TAB_PATHS.includes(location.pathname);

  if (!ready) return <BootScreen />;
  if (error && !user) return <ErrorScreen message={error} />;
  if (!user) return <BootScreen />;
  if (!user.accepted || !user.adult) return <AcceptGate />;

  return (
    <div className="safe-top app-shell min-h-screen">
      <BackButtonSync />
      <Suspense fallback={<BootScreen />}>
        <div className={showTabs ? "safe-bottom" : "pb-10"}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/catalog" element={<Catalog />} />
            <Route path="/friends" element={<Friends />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/wallet" element={<Wallet />} />
            <Route path="/offer/:id" element={<OfferPage />} />
            <Route path="/apps" element={<MyApps />} />
            <Route path="/apps/:id" element={<AppDetail />} />
            <Route path="/history" element={<History />} />
            <Route path="/withdraw" element={<Withdraw />} />
            <Route path="/achievements" element={<Achievements />} />
            <Route path="/leaderboard" element={<Leaderboard />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/support" element={<Support />} />
            <Route path="/rules" element={<Rules />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </Suspense>
      {showTabs && <TabBar />}
    </div>
  );
}

function ScrollReset() {
  const location = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  return null;
}

export default function App() {
  return (
    <SessionProvider>
      <ScrollReset />
      <Shell />
    </SessionProvider>
  );
}