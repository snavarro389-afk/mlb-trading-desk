-- Run in Supabase Dashboard > SQL Editor
create extension if not exists pgcrypto;

create table if not exists public.games (
    game_pk bigint primary key,
    game_date date not null,
    away_team text not null,
    home_team text not null,
    away_starter text,
    home_starter text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.model_versions (
    version text primary key,
    released_at timestamptz not null default now(),
    weights_json jsonb not null default '{}'::jsonb,
    thresholds_json jsonb not null default '{}'::jsonb,
    notes text
);

create table if not exists public.market_snapshots (
    snapshot_id text primary key,
    game_pk bigint references public.games(game_pk) on delete cascade,
    captured_at timestamptz not null default now(),
    market_type text not null,
    selection text not null,
    inning integer,
    half text,
    outs integer,
    away_score integer,
    home_score integer,
    base_state text,
    sportsbook text,
    selection_odds integer not null,
    opposing_odds integer not null,
    no_vig_probability numeric(8,6) not null,
    estimated_probability numeric(8,6),
    probability_source text not null default 'not available',
    estimated_edge numeric(8,6),
    ev_per_dollar numeric(10,6),
    information_quality text,
    sync_confirmed boolean,
    premarket_status text,
    readiness text,
    bullpen_context text,
    decision_label text,
    model_version text references public.model_versions(version),
    notes text,
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.bets (
    bet_id uuid primary key default gen_random_uuid(),
    snapshot_id text references public.market_snapshots(snapshot_id) on delete set null,
    game_pk bigint references public.games(game_pk) on delete set null,
    game_date date not null,
    placed_at timestamptz not null default now(),
    market_type text not null,
    selection text not null,
    entry_odds integer not null,
    stake numeric(12,2) not null check (stake >= 0),
    decision_status text,
    result text not null default 'Open',
    profit_loss numeric(12,2),
    closing_odds integer,
    settled_at timestamptz,
    notes text,
    model_version text references public.model_versions(version)
);

create table if not exists public.bet_reviews (
    bet_id uuid primary key references public.bets(bet_id) on delete cascade,
    thesis text,
    thesis_killers text,
    thesis_broken boolean,
    execution_grade text,
    thesis_grade text,
    lesson text,
    reviewed_at timestamptz not null default now()
);

create index if not exists idx_snapshots_game_time on public.market_snapshots(game_pk, captured_at desc);
create index if not exists idx_bets_date on public.bets(game_date desc);
create index if not exists idx_bets_result on public.bets(result);

alter table public.games enable row level security;
alter table public.model_versions enable row level security;
alter table public.market_snapshots enable row level security;
alter table public.bets enable row level security;
alter table public.bet_reviews enable row level security;

insert into public.model_versions (version, weights_json, thresholds_json, notes)
values (
    'v0.5.1',
    '{"starting_pitching":0.65,"matchup_offense":0.35,"offense_season":0.55,"offense_handedness":0.45}'::jsonb,
    '{"top_matchup":78,"review":64,"bullpen_limited_team_pitches":80,"bullpen_concerning_team_pitches":120}'::jsonb,
    'Supabase persistence foundation.'
)
on conflict (version) do update set
    weights_json = excluded.weights_json,
    thresholds_json = excluded.thresholds_json,
    notes = excluded.notes;
