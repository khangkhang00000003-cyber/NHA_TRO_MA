-- QUAN LY TIEN TRO: Supabase PostgreSQL schema
-- Run once in Supabase Dashboard > SQL Editor > New query > Run.
-- The app and GitHub Actions use the server-side service-role/secret key.
-- Do not put that key in browser-side code or commit it to GitHub.

create table if not exists public.rooms (
    room_no integer primary key check (room_no between 1 and 9999),
    tenant_name text not null default '',
    tenant_phone text not null default '',
    tenant_email text not null default '',
    rent_price bigint not null default 2500000 check (rent_price >= 0),
    is_active boolean not null default true,
    auto_email_enabled boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.monthly_settings (
    year integer not null check (year between 2000 and 2200),
    month integer not null check (month between 1 and 12),
    electric_rate bigint not null default 3500 check (electric_rate >= 0),
    water_rate bigint not null default 15000 check (water_rate >= 0),
    other_fee bigint not null default 150000 check (other_fee >= 0),
    auto_email_day integer not null default 1 check (auto_email_day between 1 and 28),
    updated_at timestamptz not null default now(),
    primary key (year, month)
);

create table if not exists public.monthly_bills (
    year integer not null check (year between 2000 and 2200),
    month integer not null check (month between 1 and 12),
    room_no integer not null references public.rooms(room_no),
    tenant_name text not null default '',
    tenant_phone text not null default '',
    tenant_email text not null default '',
    rent_price bigint not null default 2500000 check (rent_price >= 0),
    electricity_old bigint not null default 0 check (electricity_old >= 0),
    electricity_new bigint not null default 0 check (electricity_new >= 0),
    water_old bigint not null default 0 check (water_old >= 0),
    water_new bigint not null default 0 check (water_new >= 0),
    payment_status text not null default 'Chưa thanh toán' check (payment_status in ('Chưa thanh toán', 'Đã thanh toán')),
    note text not null default '',
    is_finalized boolean not null default false,
    auto_email_enabled boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (year, month, room_no)
);

create table if not exists public.email_logs (
    id uuid primary key default gen_random_uuid(),
    year integer not null,
    month integer not null,
    room_no integer not null,
    recipient text not null default '',
    status text not null check (status in ('Thành công', 'Thất bại', 'Bỏ qua')),
    error_message text not null default '',
    created_at timestamptz not null default now()
);

create index if not exists idx_monthly_bills_period on public.monthly_bills (year, month, room_no);
create index if not exists idx_monthly_bills_automation on public.monthly_bills (is_finalized, auto_email_enabled);
create index if not exists idx_email_logs_period on public.email_logs (year, month, room_no, status);

-- Defense in depth: RLS is enabled; the app's server-side service-role key bypasses it.
-- No public/anon policies are created, so browser-side anonymous access is denied.
alter table public.rooms enable row level security;
alter table public.monthly_settings enable row level security;
alter table public.monthly_bills enable row level security;
alter table public.email_logs enable row level security;

grant all on public.rooms to service_role;
grant all on public.monthly_settings to service_role;
grant all on public.monthly_bills to service_role;
grant all on public.email_logs to service_role;
