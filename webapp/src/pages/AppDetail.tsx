import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fmtDateTime, rub, uploadWithProgress } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { MyApp } from "../lib/types";
import { Icon, type IconName } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle, StatusBadge } from "../components/ui";
import { haptic, hapticNotify, openExternal, showAlert, showConfirm } from "../lib/telegram";


type DealMessage = { id: number; is_admin: boolean; body: string; created: string | null };
const MAX_FILES = 10;
const MAX_SIZE = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"];

interface StagedFile {
  file: File;
  preview: string | null;
}

interface ProofView {
  url: string;
  name: string;
  mime: string;
  at: number;
}

type BannerTone = "electric" | "royal" | "gold" | "emerald" | "rose" | "muted";

interface StatusBanner {
  tone: BannerTone;
  icon: IconName;
  title: string;
  text: string;
  note?: string;
}

const BANNER_TONE: Record<BannerTone, string> = {
  electric: "border-electric/30 bg-electric/10 text-electric",
  royal: "border-royal/40 bg-royal/15 text-royal-soft",
  gold: "border-gold/30 bg-gold/10 text-gold",
  emerald: "border-emerald-glow/30 bg-emerald-glow/10 text-emerald-glow",
  rose: "border-rose-alert/30 bg-rose-alert/10 text-rose-alert",
  muted: "border-indigo-400/20 bg-indigo-400/10 text-indigo-200/70",
};

/** Подпись с правильным склонением: 1 файл, 2 файла, 5 файлов. */
function filesWord(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return "файл";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "файла";
  return "файлов";
}

/** MIME по расширению — на случай, если сервер отдал пустой или общий тип. */
function guessMime(name: string): string {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return "application/pdf";
  if (ext === "png") return "image/png";
  if (ext === "webp") return "image/webp";
  if (ext === "heic" || ext === "heif") return "image/heic";
  if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
  return "";
}

/** Что показать пользователю в зависимости от статуса заявки. */
function statusBanner(app: MyApp): StatusBanner {
  const submittedNote =
    app.submitted && (app.status === "proof" || app.status === "hold")
      ? "Отправлено на проверку"
      : undefined;
  switch (app.status) {
    case "new":
      return {
        tone: "electric",
        icon: "camera",
        title: "Загрузи подтверждение",
        text: "Прикрепи скриншоты выполнения условий — после этого комплект можно отправить на проверку.",
      };
    case "proof":
      return {
        tone: "royal",
        icon: "clock",
        title: "Проверяем",
        text: submittedNote
          ? "Администратор проверяет комплект. Решение придёт в Telegram, статус обновится здесь."
          : "Проверяем подтверждения. Если ниже чего-то не хватает — загрузи файл.",
        note: submittedNote,
      };
    case "hold":
      return {
        tone: "gold",
        icon: "clock",
        title: app.hold_until ? `Ждём сеть до ${fmtDateTime(app.hold_until)}` : "Ждём сеть",
        text: "Партнёрская сеть подтверждает выполнение условий. Как только придёт ответ, награда станет доступна к выводу.",
        note: submittedNote,
      };
    case "confirmed":
      return {
        tone: "emerald",
        icon: "coin",
        title: "Начислено",
        text: `${rub(app.cashback || app.reward)} зачислено на баланс — сумму можно вывести в кошельке.`,
      };
    case "paid":
      return {
        tone: "emerald",
        icon: "check",
        title: "Выплачено",
        text: `${rub(app.cashback || app.reward)} переведено на твои реквизиты.`,
      };
    case "rejected":
      return {
        tone: "rose",
        icon: "cross",
        title: "Отклонено",
        text: app.reason || "Заявка отклонена. Причину уточни в поддержке по этой сделке.",
      };
    default:
      return {
        tone: "muted",
        icon: "clock",
        title: "Истекло",
        text: "Срок оформления заявки истёк. Возьми другое предложение в каталоге.",
      };
  }
}

function AppStatusBanner({ app }: { app: MyApp }) {
  const banner = statusBanner(app);
  return (
    <section className="px-5 pt-3">
      <div className={`flex items-start gap-3 rounded-2xl border p-4 ${BANNER_TONE[banner.tone]}`}>
        <Icon name={banner.icon} className="mt-0.5 h-5 w-5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-extrabold">{banner.title}</div>
          <p className="mt-1 text-xs leading-relaxed opacity-80">{banner.text}</p>
          {banner.note && (
            <span className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-black/25 px-2.5 py-1 text-[11px] font-bold">
              <Icon name="check" className="h-3 w-3" /> {banner.note}
            </span>
          )}
        </div>
      </div>
    </section>
  );
}

export default function AppDetail() {
  const { id } = useParams();
  const { data: app, error, reload, setData } = useLoad<MyApp>(`/apps/${id}`);
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [messages, setMessages] = useState<DealMessage[]>([]);
  const [messageText, setMessageText] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [proofView, setProofView] = useState<ProofView | null>(null);
  const [proofLoading, setProofLoading] = useState<number | null>(null);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const previewUrls = useRef<Set<string>>(new Set());
  const proofUrl = useRef<string | null>(null);

  useEffect(() => {
    const urls = previewUrls.current;
    return () => {
      urls.forEach((u) => URL.revokeObjectURL(u));
      if (proofUrl.current) URL.revokeObjectURL(proofUrl.current);
    };
  }, []);

  useEffect(() => {
    if (!app) return;
    let active = true;
    api.get<DealMessage[]>("/apps/" + app.id + "/messages")
      .then((items) => { if (active) setMessages(items); })
      .catch(() => { if (active) setMessages([]); });
    return () => { active = false; };
  }, [app?.id]);

  async function sendMessage() {
    if (!app || !messageText.trim() || sendingMessage) return;
    setSendingMessage(true);
    try {
      const created = await api.post<DealMessage>("/apps/" + app.id + "/messages", { body: messageText.trim() });
      setMessages((prev) => [...prev, created]);
      setMessageText("");
      hapticNotify("success");
    } catch (e) {
      showAlert(e instanceof Error ? e.message : "Не удалось отправить сообщение.");
    } finally {
      setSendingMessage(false);
    }
  }

  function pickFiles(files: FileList | null) {
    if (!files) return;
    const next: StagedFile[] = [];
    for (const file of Array.from(files)) {
      if (staged.length + next.length >= MAX_FILES) {
        showAlert(`Максимум ${MAX_FILES} файлов за одну отправку.`);
        break;
      }
      if (!ALLOWED_TYPES.includes(file.type)) {
        showAlert(`Файл «${file.name}»: поддерживаются JPG, PNG, WebP, HEIC и PDF.`);
        continue;
      }
      if (file.size > MAX_SIZE) {
        showAlert(`Файл «${file.name}» больше 10 МБ.`);
        continue;
      }
      const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
      if (preview) previewUrls.current.add(preview);
      next.push({ file, preview });
    }
    if (next.length > 0) {
      setUploadError(null);
      setUploadNotice(null);
      setStaged((prev) => [...prev, ...next]);
    }
    if (fileInput.current) fileInput.current.value = "";
  }

  function removeStaged(index: number) {
    setStaged((prev) => {
      const item = prev[index];
      if (item?.preview) {
        URL.revokeObjectURL(item.preview);
        previewUrls.current.delete(item.preview);
      }
      return prev.filter((_, i) => i !== index);
    });
  }

  function closeProof() {
    if (proofUrl.current) {
      URL.revokeObjectURL(proofUrl.current);
      proofUrl.current = null;
    }
    setProofView(null);
  }

  async function openProof(at: number) {
    if (!app) return;
    const item = app.proofs[at];
    if (!item) return;
    setProofLoading(at);
    haptic("light");
    try {
      const blob = await api.blob(`/apps/${app.id}/proofs/${at}/file`);
      const type = blob.type && blob.type !== "application/octet-stream" ? blob.type : guessMime(item.name);
      const url = URL.createObjectURL(blob);
      if (proofUrl.current) URL.revokeObjectURL(proofUrl.current);
      proofUrl.current = url;
      setProofView({ url, name: item.name, mime: type, at });
    } catch (e) {
      hapticNotify("error");
      showAlert(e instanceof Error ? e.message : "Не удалось открыть файл.");
    } finally {
      setProofLoading(null);
    }
  }

  async function upload() {
    if (!app || staged.length === 0) return;
    const sentCount = staged.length;
    setUploading(true);
    setProgress(0);
    setUploadError(null);
    setUploadNotice(null);
    haptic("medium");
    const form = new FormData();
    staged.forEach((s) => form.append("files", s.file, s.file.name));
    try {
      const updated = await uploadWithProgress<MyApp>(`/apps/${app.id}/proofs`, form, setProgress);
      staged.forEach((s) => {
        if (s.preview) {
          URL.revokeObjectURL(s.preview);
          previewUrls.current.delete(s.preview);
        }
      });
      setStaged([]);
      setData(updated);
      setUploadNotice(`Загружено: ${sentCount} ${filesWord(sentCount)}. Список ниже обновлён.`);
      hapticNotify("success");
      void reload();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Ошибка загрузки. Файлы сохранены — попробуй ещё раз.");
      hapticNotify("error");
    } finally {
      setUploading(false);
    }
  }

  async function submit() {
    if (!app) return;
    const ok = await showConfirm(
      "Отправить заявку на проверку? После отправки администратор проверит подтверждения и условия.",
    );
    if (!ok) return;
    setSubmitting(true);
    haptic("medium");
    try {
      const updated = await api.post<MyApp>(`/apps/${app.id}/submit`);
      setData(updated);
      hapticNotify("success");
      showAlert("Заявка отправлена на проверку. Статус обновится после решения администратора.");
    } catch (e) {
      hapticNotify("error");
      showAlert(e instanceof Error ? e.message : "Не удалось отправить заявку.");
      void reload();
    } finally {
      setSubmitting(false);
    }
  }

  const receivedProofs = new Set(app?.proofs_received ?? []);
  const missingProofs = app ? app.proofs_required.filter((_, i) => !receivedProofs.has(i)) : [];

  return (
    <div>
      <PageHeader title="Заявка" back="/apps" />
      {error && <ErrorState message={error} onRetry={() => void reload()} />}
      {!app && !error && <ListSkeleton rows={3} />}
      {app && (
        <>
          <section className="px-5">
            <div className="card-glass p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-navy-800 text-xl">
                  {app.image_url ? (
                    <img src={app.image_url} alt="" className="h-full w-full object-cover" />
                  ) : (
                    <span>{app.emoji}</span>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-semibold uppercase tracking-wide text-indigo-300/70">
                    {app.brand}
                  </div>
                  <div className="truncate text-sm font-bold">{app.offer_name}</div>
                </div>
                <div className="shrink-0 text-base font-extrabold text-gold-gradient">
                  {rub(app.cashback || app.reward)}
                </div>
              </div>
              <div className="mt-4 flex items-center justify-between">
                <StatusBadge status={app.status} />
                <span className="text-[12px] text-indigo-300/70">от {fmtDateTime(app.created)}</span>
              </div>
              {["new", "proof", "hold", "confirmed", "paid"].includes(app.status) && (() => {
                const order = ["new", "proof", "hold", "paid"];
                const idx = app.status === "confirmed" ? 3 : order.indexOf(app.status);
                const labels = ["Оформлено", "Доказательства", "Проверка сети", "Выплата"];
                return (
                  <div className="mt-4 grid grid-cols-4 gap-1.5" aria-label="Этапы заявки">
                    {labels.map((label, i) => (
                      <div key={label} className="min-w-0">
                        <div className={`h-1.5 rounded-full ${i <= idx ? "bg-electric" : "bg-white/10"}`} />
                        <div className={`mt-1.5 truncate text-[10px] font-semibold ${i <= idx ? "text-electric" : "text-indigo-300/45"}`}>{label}</div>
                      </div>
                    ))}
                  </div>
                );
              })()}
              {app.booking_until && (app.status === "new" || app.status === "proof") && (
                <div className="mt-3 flex items-center gap-2 rounded-2xl bg-electric/10 p-3 text-xs text-electric">
                  <Icon name="clock" className="h-4 w-4 shrink-0" />
                  Бронь предложения до {fmtDateTime(app.booking_until)}
                </div>
              )}
              {app.personal_link && (app.status === "new" || app.status === "proof") && (
                <button
                  className="btn-primary mt-4 w-full"
                  onClick={() => {
                    haptic("light");
                    openExternal(app.personal_link!);
                  }}
                >
                  <Icon name="share" className="h-4 w-4" /> Перейти к оформлению
                </button>
              )}
            </div>
          </section>

          <AppStatusBanner app={app} />

          {app.more_info_text && (
            <section className="px-5 pt-3">
              <div className="card-glass p-4 text-xs leading-relaxed text-indigo-200/70">
                <div className="mb-1 font-bold text-indigo-100">Важно</div>
                <p className="whitespace-pre-line">{app.more_info_text}</p>
              </div>
            </section>
          )}

          <SectionTitle
            action={
              <span className="text-[11px] font-semibold text-indigo-300/45">
                {app.proofs.length} {filesWord(app.proofs.length)}
              </span>
            }
          >
            Доказательства
          </SectionTitle>
          <section className="space-y-2 px-5">
            {app.proofs.length === 0 ? (
              <div className="card-glass px-4 py-5 text-center text-xs leading-relaxed text-indigo-300/60">
                Пока ничего не загружено.
                {app.can_upload ? " Добавь скриншоты или PDF в блоке ниже." : ""}
              </div>
            ) : (
              app.proofs.map((p, i) => (
                <button
                  key={i}
                  type="button"
                  className="card-glass flex w-full items-center gap-3 p-3.5 text-left transition active:scale-[0.99] disabled:opacity-60"
                  onClick={() => void openProof(i)}
                  disabled={proofLoading !== null}
                  aria-label={`Открыть файл ${p.name}`}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-electric/10 text-electric">
                    <Icon name={proofLoading === i ? "refresh" : "doc"} className="h-5 w-5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-bold">{p.name}</span>
                    <span className="block text-[12px] text-indigo-300/45">
                      {p.label ? `${p.label} · ` : ""}
                      {fmtDateTime(p.uploaded_at)}
                    </span>
                  </span>
                  {p.duplicate_suspected && (
                    <span className="shrink-0 rounded-full border border-gold/30 bg-gold/10 px-2 py-1 text-[11px] font-bold text-gold">
                      возможен дубликат
                    </span>
                  )}
                  <Icon name="chevron-right" className="h-4 w-4 shrink-0 text-indigo-300/40" />
                </button>
              ))
            )}
          </section>

          <SectionTitle>Чего не хватает</SectionTitle>
          <section className="px-5">
            <div className="card-glass space-y-2.5 p-5">
              {app.proofs_required.length === 0 ? (
                <p className="text-xs leading-relaxed text-indigo-200/65">
                  Для этого предложения список пунктов не задан. Уже загружено: {app.proofs.length}{" "}
                  {filesWord(app.proofs.length)}.
                </p>
              ) : (
                <>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="text-indigo-300/60">Пункты подтверждения</span>
                    <span
                      className={`font-bold ${missingProofs.length > 0 ? "text-gold" : "text-emerald-glow"}`}
                    >
                      {missingProofs.length > 0
                        ? `осталось ${missingProofs.length} из ${app.proofs_required.length}`
                        : "всё собрано"}
                    </span>
                  </div>
                  {app.proofs_required.map((label, i) => {
                    const done = receivedProofs.has(i);
                    return (
                      <div key={i} className="flex items-center gap-3 text-xs">
                        <span
                          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                            done ? "bg-emerald-glow/15 text-emerald-glow" : "bg-gold/10 text-gold"
                          }`}
                        >
                          <Icon name={done ? "check" : "plus"} className="h-3.5 w-3.5" />
                        </span>
                        <span className={done ? "text-indigo-300/40 line-through" : "text-indigo-100"}>
                          {label}
                        </span>
                        {!done && (
                          <span className="ml-auto shrink-0 text-[11px] font-bold text-gold">нужно</span>
                        )}
                      </div>
                    );
                  })}
                  {missingProofs.length === 0 && (
                    <p className="pt-1 text-[12px] text-indigo-300/50">
                      Все пункты закрыты — комплект можно отправлять на проверку.
                    </p>
                  )}
                </>
              )}
            </div>
          </section>

          {app.can_upload && (
            <>
              <SectionTitle>Загрузить файлы</SectionTitle>
              <section className="px-5">
                <div className="card-glass space-y-3 p-5">
                  <input
                    ref={fileInput}
                    type="file"
                    multiple
                    accept=".jpg,.jpeg,.png,.webp,.heic,.pdf,image/jpeg,image/png,image/webp,image/heic,application/pdf"
                    className="hidden"
                    onChange={(e) => pickFiles(e.target.files)}
                    aria-label="Выбрать файлы подтверждений"
                  />
                  <button
                    className="btn-ghost w-full"
                    disabled={uploading}
                    onClick={() => fileInput.current?.click()}
                  >
                    <Icon name="camera" className="h-4 w-4" /> Выбрать файлы (до {MAX_FILES}, 10 МБ каждый)
                  </button>

                  {staged.length > 0 && (
                    <div className="grid grid-cols-3 gap-2">
                      {staged.map((s, i) => (
                        <div key={i} className="relative overflow-hidden rounded-xl border border-royal/25 bg-navy-950">
                          {s.preview ? (
                            <img src={s.preview} alt={s.file.name} className="h-20 w-full object-cover" />
                          ) : (
                            <div className="flex h-20 w-full items-center justify-center">
                              <Icon name="doc" className="h-7 w-7 text-indigo-300/70" />
                            </div>
                          )}
                          <button
                            className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-navy-950/90 text-rose-alert"
                            onClick={() => removeStaged(i)}
                            aria-label={`Убрать ${s.file.name}`}
                            disabled={uploading}
                          >
                            <Icon name="cross" className="h-3.5 w-3.5" />
                          </button>
                          <div className="truncate px-1.5 py-1 text-[9px] text-indigo-300/75">{s.file.name}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {uploading && (
                    <div>
                      <div className="mb-1 flex justify-between text-[12px] text-indigo-300/75">
                        <span>Загрузка…</span>
                        <span className="font-bold text-electric">{progress}%</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-navy-800">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-royal-soft to-electric transition-all"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {uploadError && (
                    <div className="rounded-2xl border border-rose-alert/30 bg-rose-alert/10 p-3 text-xs text-rose-alert">
                      {uploadError}
                    </div>
                  )}

                  {uploadNotice && (
                    <div className="flex items-center gap-2 rounded-2xl border border-emerald-glow/30 bg-emerald-glow/10 p-3 text-xs text-emerald-glow">
                      <Icon name="check" className="h-4 w-4 shrink-0" /> {uploadNotice}
                    </div>
                  )}

                  {staged.length > 0 && (
                    <button className="btn-primary w-full" disabled={uploading} onClick={() => void upload()}>
                      <Icon name="arrow-up" className="h-4 w-4" />
                      {uploading ? "Отправляю…" : `Отправить ${staged.length} файл(ов)`}
                    </button>
                  )}

                  {app.submitted && (
                    <p className="text-[11px] leading-relaxed text-indigo-300/45">
                      Комплект уже отправлен на проверку. Новый файл отправит его повторно.
                    </p>
                  )}

                  <p className="text-[12px] leading-relaxed text-indigo-300/45">
                    Файлы хранятся приватно и доступны только тебе и администратору. Не загружай
                    паспортные сканы, CVV/CVC, PIN-коды, пароли, коды из SMS и полные номера карт.
                  </p>
                </div>
              </section>
            </>
          )}

          {app.can_submit && !app.submitted && (
            <section className="px-5 pt-4">
              <button className="btn-gold w-full" disabled={submitting} onClick={() => void submit()}>
                <Icon name="check" className="h-4 w-4" />
                {submitting ? "Отправляю…" : "Отправить на проверку"}
              </button>
            </section>
          )}


          <SectionTitle>Поддержка по этой сделке</SectionTitle>
          <section className="px-5">
            <div className="card-glass space-y-3 p-4">
              <p className="text-xs leading-relaxed text-indigo-200/60">Вопросы по условиям, проверке или выплате можно обсудить здесь. Ответ администратора появится в переписке и придёт в Telegram.</p>
              {messages.length > 0 && <div className="max-h-72 space-y-2 overflow-y-auto">
                {messages.map((msg) => <div key={msg.id} className={msg.is_admin ? "flex justify-start" : "flex justify-end"}>
                  <div className={"max-w-[90%] rounded-2xl px-3 py-2 text-xs " + (msg.is_admin ? "bg-electric/10 text-indigo-100" : "bg-royal/20 text-indigo-100")}>
                    <div className="mb-1 text-[10px] font-bold text-indigo-300/70">{msg.is_admin ? "Поддержка BONVERA" : "Вы"}</div>
                    <p className="whitespace-pre-wrap break-words">{msg.body}</p>
                    {msg.created && <div className="mt-1 text-[10px] text-indigo-300/40">{fmtDateTime(msg.created)}</div>}
                  </div>
                </div>)}
              </div>}
              <textarea value={messageText} onChange={(e) => setMessageText(e.target.value)} maxLength={2000} rows={3} placeholder="Напишите сообщение по этой сделке…" className="w-full resize-y rounded-xl border border-royal/25 bg-navy-950/70 p-3 text-sm text-white placeholder:text-indigo-300/35 focus:border-electric focus:outline-none" />
              <button className="btn-primary w-full" disabled={sendingMessage || !messageText.trim()} onClick={() => void sendMessage()}>
                <Icon name="support" className="h-4 w-4" /> {sendingMessage ? "Отправляю…" : "Отправить в поддержку"}
              </button>
            </div>
          </section>

          {app.events.length > 0 && (
            <>
              <SectionTitle>История заявки</SectionTitle>
              <section className="px-5 pb-8">
                <div className="card-glass space-y-4 p-5">
                  {app.events.map((ev) => (
                    <div key={ev.id} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-electric shadow-glow-electric" />
                        <span className="w-px flex-1 bg-royal/25" />
                      </div>
                      <div className="min-w-0 pb-1">
                        <div className="text-xs font-bold">{ev.event}</div>
                        {ev.comment && (
                          <div className="mt-0.5 text-[12px] leading-relaxed text-indigo-200/60">{ev.comment}</div>
                        )}
                        <div className="mt-0.5 text-[12px] text-indigo-300/40">{fmtDateTime(ev.created)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          {proofView && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/90 p-4"
              role="dialog"
              aria-modal="true"
              aria-label={proofView.name}
              onClick={closeProof}
            >
              <div
                className="card-glass max-h-[90vh] w-full max-w-3xl overflow-auto p-3"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-extrabold">{proofView.name}</div>
                    <div className="text-[11px] text-indigo-300/50">
                      Файл {proofView.at + 1} из {app.proofs.length} · {proofView.mime || "файл"}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {app.proofs.length > 1 && (
                      <>
                        <button
                          type="button"
                          className="btn-ghost px-3 py-2 text-xs"
                          onClick={() =>
                            void openProof((proofView.at + app.proofs.length - 1) % app.proofs.length)
                          }
                          disabled={proofLoading !== null}
                          aria-label="Предыдущий файл"
                        >
                          <Icon name="chevron-left" className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          className="btn-ghost px-3 py-2 text-xs"
                          onClick={() => void openProof((proofView.at + 1) % app.proofs.length)}
                          disabled={proofLoading !== null}
                          aria-label="Следующий файл"
                        >
                          <Icon name="chevron-right" className="h-4 w-4" />
                        </button>
                      </>
                    )}
                    <a
                      href={proofView.url}
                      download={proofView.name}
                      className="btn-ghost px-3 py-2 text-xs"
                    >
                      Скачать
                    </a>
                    <button type="button" className="btn-ghost px-3 py-2 text-xs" onClick={closeProof}>
                      <Icon name="cross" className="h-4 w-4" /> Закрыть
                    </button>
                  </div>
                </div>
                {proofView.mime === "application/pdf" ? (
                  <iframe
                    src={proofView.url}
                    title={proofView.name}
                    className="h-[70vh] w-full rounded-xl bg-white"
                  />
                ) : proofView.mime.startsWith("image/") && !/hei[cf]/.test(proofView.mime) ? (
                  <img
                    src={proofView.url}
                    alt={proofView.name}
                    className="mx-auto max-h-[70vh] max-w-full rounded-xl object-contain"
                  />
                ) : (
                  <div className="rounded-xl border border-royal/25 bg-navy-950/60 p-6 text-center text-xs text-indigo-200/70">
                    <Icon name="doc" className="mx-auto h-8 w-8 text-electric" />
                    <p className="mt-2 leading-relaxed">
                      Предпросмотр для этого формата недоступен — скачай файл, чтобы открыть его.
                    </p>
                    <a
                      href={proofView.url}
                      download={proofView.name}
                      className="btn-primary mt-3 px-4 py-2 text-xs"
                    >
                      Скачать файл
                    </a>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}