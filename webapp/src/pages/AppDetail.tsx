import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, fmtDateTime, rub, uploadWithProgress } from "../lib/api";
import { useLoad } from "../lib/useLoad";
import type { MyApp } from "../lib/types";
import { Icon } from "../components/Icon";
import { ErrorState, ListSkeleton, PageHeader, SectionTitle, StatusBadge } from "../components/ui";
import { haptic, hapticNotify, openExternal, showAlert, showConfirm } from "../lib/telegram";

const MAX_FILES = 10;
const MAX_SIZE = 10 * 1024 * 1024;
const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic", "application/pdf"];

interface StagedFile {
  file: File;
  preview: string | null;
}

export default function AppDetail() {
  const { id } = useParams();
  const { data: app, error, reload, setData } = useLoad<MyApp>(`/apps/${id}`);
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const previewUrls = useRef<Set<string>>(new Set());

  useEffect(() => {
    const urls = previewUrls.current;
    return () => {
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, []);

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

  async function upload() {
    if (!app || staged.length === 0) return;
    setUploading(true);
    setProgress(0);
    setUploadError(null);
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
      hapticNotify("success");
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
                  <div className="truncate text-[11px] font-semibold uppercase tracking-wide text-indigo-300/55">
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
                <span className="text-[11px] text-indigo-300/50">от {fmtDateTime(app.created)}</span>
              </div>
              {app.reason && (
                <div className="mt-3 rounded-2xl border border-rose-alert/30 bg-rose-alert/10 p-3 text-xs leading-relaxed text-rose-alert">
                  {app.reason}
                </div>
              )}
              {app.status === "hold" && app.hold_until && (
                <div className="mt-3 flex items-center gap-2 rounded-2xl bg-gold/10 p-3 text-xs text-gold">
                  <Icon name="clock" className="h-4 w-4 shrink-0" />
                  Холд партнёрской сети до {fmtDateTime(app.hold_until)}. После подтверждения сумма
                  станет доступна к выводу.
                </div>
              )}
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

          {app.more_info_text && (
            <section className="px-5 pt-3">
              <div className="card-glass p-4 text-xs leading-relaxed text-indigo-200/70">
                <div className="mb-1 font-bold text-indigo-100">Важно</div>
                <p className="whitespace-pre-line">{app.more_info_text}</p>
              </div>
            </section>
          )}

          {app.proofs_required.length > 0 && (
            <>
              <SectionTitle>Подтверждения</SectionTitle>
              <section className="px-5">
                <div className="card-glass space-y-2.5 p-5">
                  {app.proofs_required.map((label, i) => {
                    const done = app.proofs_received.includes(i);
                    return (
                      <div key={i} className="flex items-center gap-3 text-xs">
                        <span
                          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
                            done ? "bg-emerald-glow/15 text-emerald-glow" : "bg-navy-800 text-indigo-300/50"
                          }`}
                        >
                          <Icon name={done ? "check" : "camera"} className="h-3.5 w-3.5" />
                        </span>
                        <span className={done ? "text-indigo-100" : "text-indigo-200/65"}>{label}</span>
                      </div>
                    );
                  })}
                </div>
              </section>
            </>
          )}

          {app.proofs.length > 0 && (
            <section className="space-y-2 px-5 pt-3">
              {app.proofs.map((p, i) => (
                <div key={i} className="card-glass flex items-center gap-3 p-3.5">
                  <Icon name="doc" className="h-5 w-5 shrink-0 text-electric" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-bold">{p.name}</div>
                    <div className="text-[10px] text-indigo-300/45">{fmtDateTime(p.uploaded_at)}</div>
                  </div>
                  {p.duplicate_suspected && (
                    <span className="shrink-0 rounded-full border border-gold/30 bg-gold/10 px-2 py-1 text-[10px] font-bold text-gold">
                      возможен дубликат
                    </span>
                  )}
                </div>
              ))}
            </section>
          )}

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
                              <Icon name="doc" className="h-7 w-7 text-indigo-300/50" />
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
                          <div className="truncate px-1.5 py-1 text-[9px] text-indigo-300/60">{s.file.name}</div>
                        </div>
                      ))}
                    </div>
                  )}

                  {uploading && (
                    <div>
                      <div className="mb-1 flex justify-between text-[11px] text-indigo-300/60">
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

                  {staged.length > 0 && (
                    <button className="btn-primary w-full" disabled={uploading} onClick={() => void upload()}>
                      <Icon name="arrow-up" className="h-4 w-4" />
                      {uploading ? "Отправляю…" : `Отправить ${staged.length} файл(ов)`}
                    </button>
                  )}

                  <p className="text-[10px] leading-relaxed text-indigo-300/45">
                    Файлы хранятся приватно и доступны только тебе и администратору. Не загружай
                    паспортные сканы, CVV/CVC, PIN-коды, пароли, коды из SMS и полные номера карт.
                  </p>
                </div>
              </section>
            </>
          )}

          {app.can_submit && (
            <section className="px-5 pt-4">
              <button className="btn-gold w-full" disabled={submitting} onClick={() => void submit()}>
                <Icon name="check" className="h-4 w-4" />
                {submitting ? "Отправляю…" : "Отправить на проверку"}
              </button>
            </section>
          )}

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
                          <div className="mt-0.5 text-[11px] leading-relaxed text-indigo-200/60">{ev.comment}</div>
                        )}
                        <div className="mt-0.5 text-[10px] text-indigo-300/40">{fmtDateTime(ev.created)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}