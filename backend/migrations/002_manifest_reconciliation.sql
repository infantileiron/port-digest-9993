-- 应到清单、按站日对账、分发前放行单与站日并发锁。
-- 既有 arrivals 增加修订号：台账每次写入都会让该站日旧核对失效。

ALTER TABLE public.arrivals ADD COLUMN IF NOT EXISTS revision integer DEFAULT 0 NOT NULL;

CREATE TABLE IF NOT EXISTS public.manifests (
    id integer NOT NULL,
    station character varying(30) NOT NULL,
    report_day character varying(10) NOT NULL,
    version integer NOT NULL,
    status character varying(20),
    items json,
    checksum character varying(64),
    item_count integer,
    note text,
    created_by character varying(100),
    created_at character varying(40),
    reconciled_at character varying(40)
);
CREATE SEQUENCE IF NOT EXISTS public.manifests_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.manifests_id_seq OWNED BY public.manifests.id;
ALTER TABLE ONLY public.manifests ALTER COLUMN id SET DEFAULT nextval('public.manifests_id_seq'::regclass);
ALTER TABLE ONLY public.manifests ADD CONSTRAINT manifests_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.manifests ADD CONSTRAINT uq_manifest_station_day_version UNIQUE (station, report_day, version);

CREATE TABLE IF NOT EXISTS public.reconciliations (
    id integer NOT NULL,
    manifest_id integer NOT NULL,
    station character varying(30),
    report_day character varying(10),
    manifest_version integer,
    status character varying(20),
    manifest_checksum character varying(64),
    ledger_checksum character varying(64),
    manifest_total integer,
    ledger_total integer,
    matched integer,
    completed integer,
    missing integer,
    pending integer,
    unplanned integer,
    balanced boolean,
    details json,
    checked_by character varying(100),
    checked_at character varying(40),
    invalidated_at character varying(40),
    invalid_reason character varying(200)
);
CREATE SEQUENCE IF NOT EXISTS public.reconciliations_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.reconciliations_id_seq OWNED BY public.reconciliations.id;
ALTER TABLE ONLY public.reconciliations ALTER COLUMN id SET DEFAULT nextval('public.reconciliations_id_seq'::regclass);
ALTER TABLE ONLY public.reconciliations ADD CONSTRAINT reconciliations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.reconciliations ADD CONSTRAINT reconciliations_manifest_id_fkey FOREIGN KEY (manifest_id) REFERENCES public.manifests(id);

CREATE TABLE IF NOT EXISTS public.distribution_gates (
    id integer NOT NULL,
    subscription_id integer NOT NULL,
    report_day character varying(10) NOT NULL,
    state character varying(20),
    reason character varying(300),
    blocking json,
    attempts integer,
    receipt_id integer,
    first_blocked_at character varying(40),
    last_checked_at character varying(40),
    updated_at character varying(40)
);
CREATE SEQUENCE IF NOT EXISTS public.distribution_gates_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.distribution_gates_id_seq OWNED BY public.distribution_gates.id;
ALTER TABLE ONLY public.distribution_gates ALTER COLUMN id SET DEFAULT nextval('public.distribution_gates_id_seq'::regclass);
ALTER TABLE ONLY public.distribution_gates ADD CONSTRAINT distribution_gates_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.distribution_gates ADD CONSTRAINT uq_gate_subscription_day UNIQUE (subscription_id, report_day);
ALTER TABLE ONLY public.distribution_gates ADD CONSTRAINT distribution_gates_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES public.subscriptions(id);

CREATE TABLE IF NOT EXISTS public.day_locks (
    id integer NOT NULL,
    station character varying(30) NOT NULL,
    report_day character varying(10) NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS public.day_locks_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.day_locks_id_seq OWNED BY public.day_locks.id;
ALTER TABLE ONLY public.day_locks ALTER COLUMN id SET DEFAULT nextval('public.day_locks_id_seq'::regclass);
ALTER TABLE ONLY public.day_locks ADD CONSTRAINT day_locks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.day_locks ADD CONSTRAINT uq_day_lock_station_day UNIQUE (station, report_day);
