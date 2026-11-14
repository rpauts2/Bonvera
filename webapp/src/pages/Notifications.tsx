import { useEffect } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { NotificationItem } from "../lib/types";
import { Icon, type IconName } from "../components/Icon";
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from "../components/ui";

const KIND_ICON: Record<string, IconName> = {
  deal: "doc",
  payout: "wallet",
  bonus: "gift",
};

export default function Notifications() {
  const { data, error, reload } = useLoad<NotificationItem[]>("/notifications");

  useEffect(() => {
    if (data) void api.post("/notifications/read").catch(() => undefined);
  }, [data]);

  return (
    <div>
      <PageHeader title="Уведомления" back="/" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!data && !error && <ListSkeleton rows={4} />}
      {data && data.length === 0 && (
        <EmptyState
          icon="bell"
          title="Уведомлений нет"
          text="Здесь появятся статусы заявок, решения по выплатам и начисления бонусов."
        />
      )}
      {data && data.length > 0 && (
        <div className="space-y-2 px-5 pb-6">
          {data.map((n) => {
            const body = (
              <div className="card-glass flex gap-3 p-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-royal/15 text-royal-soft">
                  <Icon name={KIND_ICON[n.kind] ?? "bell"} className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-bold">{n.title}</div>
                  <p className="mt-0.5 text-xs leading-relaxed text-indigo-200/65">{n.text}</p>
                  <div className="mt-1 text-[12px] text-indigo-300/40">{fmtDateTime(n.created)}</div>
                </div>
                {n.app_id != null && (
                  <Icon name="chevron-right" className="mt-1 h-4 w-4 shrink-0 text-indigo-300/40" />
                )}
              </div>
            );
            return n.app_id != null ? (
              <Link key={n.id} to={`/apps/${n.app_id}`} className="block">
                {body}
              </Link>
            ) : (
              <div key={n.id}>{body}</div>
            );
          })}
        </div>
      )}
    </div>
  );
}