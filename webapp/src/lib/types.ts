export interface UserProfile {
  id: number;
  username: string | null;
  name: string | null;
  accepted: boolean;
  adult: boolean;
  age_years: number | null;
  balance: number;
  banned: boolean;
  sbp_bank: string;
  sbp_phone_masked: string | null;
  referrer_id: number | null;
  created: string;
  confirmed_orders: number;
  level: number;
}

export interface WalletSummary {
  available: number;
  pending_setup: number;
  review: number;
  hold: number;
  reserved: number;
  paid_total: number;
  referral_earned: number;
  min_withdraw: number;
}

export interface OfferCard {
  id: number;
  code: string;
  name: string;
  brand: string;
  brand_slug: string;
  emoji: string;
  category: "cards" | "bk" | "mfo" | "cpl";
  kind: string;
  reward: number;
  condition: string;
  hold_days: number;
  purchase_min: number;
  age_min: number;
  age_max: number;
  image_url: string;
  enabled: boolean;
  has_partner_link: boolean;
  network_status: string;
  available: boolean;
  unavailable_reason: string | null;
}

export interface OfferDetail extends OfferCard {
  action: string;
  rules: string;
  notes: string;
  source_url: string;
  verification_steps: string[];
  required_proofs: string[];
  mfo_info: { psk?: string; rate?: string; term?: string; registry?: string } | null;
  forbidden: string[];
  allowed: string[];
  slots_left_today: number | null;
  already_taken: boolean;
}

export type AppStatus = "new" | "proof" | "hold" | "confirmed" | "paid" | "rejected" | "expired";

export interface DealEvent {
  id: number;
  event: string;
  from_status: string;
  to_status: string;
  comment: string;
  created: string;
}

export interface ProofItem {
  index: number | null;
  label: string;
  kind: string;
  name: string;
  uploaded_at: string;
  duplicate_suspected: boolean;
}

export interface MyApp {
  id: number;
  offer_id: number;
  offer_name: string;
  brand: string;
  emoji: string;
  category: string;
  image_url: string;
  status: AppStatus;
  status_ru: string;
  reward: number;
  cashback: number;
  condition: string;
  created: string;
  hold_until: string | null;
  booking_until: string | null;
  reason: string;
  personal_link: string | null;
  proofs_required: string[];
  proofs_received: number[];
  proofs: ProofItem[];
  events: DealEvent[];
  can_upload: boolean;
  can_submit: boolean;
  submitted: boolean;
  more_info_text: string | null;
}

export interface WalletEntry {
  id: number;
  amount: number;
  kind: string;
  kind_ru: string;
  ref: string;
  note: string;
  created: string;
}

export interface Withdrawal {
  id: number;
  amount: number;
  bank: string;
  status: string;
  status_ru: string;
  created: string;
  paid_at: string | null;
  admin_note: string;
  can_cancel: boolean;
  events: DealEvent[];
}

export type TaskKey = "channel" | "referral" | "first_order" | "ten_orders";

export interface TaskState {
  key: TaskKey;
  title: string;
  description: string;
  reward: number;
  done: boolean;
  progress: number;
  target: number;
  action: "check_subscription" | "invite" | "order" | "orders";
  channel_url: string | null;
  claimable: boolean;
  hint: string | null;
}

export interface FriendsInfo {
  ref_link: string;
  share_link: string;
  invited: number;
  qualified: number;
  referral_earned: number;
  bonus_earned: number;
  ref_percent: number;
  history: WalletEntry[];
}

export interface LeaderboardRow {
  rank: number;
  display: string;
  value: number;
  is_me: boolean;
}

export interface Leaderboard {
  period: "month" | "all";
  rows: LeaderboardRow[];
  me: { rank: number | null; value: number };
}

export interface Achievement {
  key: string;
  title: string;
  description: string;
  icon: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

export interface Dashboard {
  wallet: WalletSummary;
  confirmed_orders: number;
  ten_progress: number;
  tasks_done: number;
  tasks_total: number;
  referral: { invited: number; qualified: number; earned: number };
  /** Персональная реферальная ссылка для шеринга с главной. */
  ref_link: string;
  /** Официальный канал, если он настроен. */
  channel_url: string | null;
  popular_offers: OfferCard[];
  achievements_preview: Achievement[];
  /** Последние события пользователя (заявки, выплаты, бонусы). */
  recent_events: NotificationItem[];
  unread_notifications: number;
}

export interface NotificationItem {
  id: string;
  kind: "deal" | "payout" | "bonus";
  title: string;
  text: string;
  created: string;
  app_id: number | null;
}

export interface AuthResult {
  token: string;
  expires_at: string;
  user: UserProfile;
}

export interface ApiEnvelope<T> {
  ok: boolean;
  data?: T;
  err?: { code: string; message: string };
}

export interface MetaInfo {
  banks: string[];
  min_withdraw: number;
  ref_percent: number;
  support_url: string | null;
  channel_url: string | null;
  bot_username: string | null;
}

export interface WalletData {
  summary: WalletSummary;
  entries: WalletEntry[];
}

export interface WithdrawalsData {
  requests: Withdrawal[];
  banks: string[];
  min_withdraw: number;
  available: number;
}

export interface TakeResult {
  app_id: number;
}