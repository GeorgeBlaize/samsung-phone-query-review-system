-- PostgreSQL schema (generated from app/db/models.py; the app creates it automatically via SQLAlchemy)

CREATE TABLE phones (
	id SERIAL NOT NULL, 
	slug VARCHAR(160) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	brand VARCHAR(60) NOT NULL, 
	url VARCHAR(300) NOT NULL, 
	image_url VARCHAR(300), 
	announced VARCHAR(120), 
	release_status VARCHAR(200), 
	release_year INTEGER, 
	dimensions VARCHAR(200), 
	weight_g FLOAT, 
	build TEXT, 
	ip_rating VARCHAR(40), 
	display_size_in FLOAT, 
	display_type TEXT, 
	display_resolution VARCHAR(200), 
	refresh_rate_hz INTEGER, 
	ppi INTEGER, 
	peak_brightness_nits INTEGER, 
	os VARCHAR(200), 
	chipset VARCHAR(200), 
	cpu TEXT, 
	gpu VARCHAR(200), 
	ram_gb FLOAT, 
	storage_options VARCHAR(200), 
	max_storage_gb INTEGER, 
	main_camera_mp FLOAT, 
	main_camera_count INTEGER, 
	main_camera_summary TEXT, 
	main_camera_video TEXT, 
	selfie_camera_mp FLOAT, 
	optical_zoom_x FLOAT, 
	battery_mah INTEGER, 
	charging_wired_w FLOAT, 
	charging_wireless_w FLOAT, 
	battery_active_use_h FLOAT, 
	battery_endurance_h FLOAT, 
	antutu_score INTEGER, 
	antutu_version VARCHAR(20), 
	geekbench_score INTEGER, 
	geekbench_version VARCHAR(20), 
	price_usd FLOAT, 
	price_text VARCHAR(200), 
	colors TEXT, 
	scraped_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_phones_slug ON phones (slug);

CREATE INDEX ix_phones_name ON phones (name);

CREATE TABLE benchmarks (
	id SERIAL NOT NULL, 
	phone_id INTEGER NOT NULL, 
	name VARCHAR(60) NOT NULL, 
	score FLOAT, 
	unit VARCHAR(30), 
	version VARCHAR(60), 
	raw VARCHAR(300) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(phone_id) REFERENCES phones (id) ON DELETE CASCADE
);

CREATE INDEX ix_benchmarks_phone_id ON benchmarks (phone_id);

CREATE TABLE prices (
	id SERIAL NOT NULL, 
	phone_id INTEGER NOT NULL, 
	currency VARCHAR(8) NOT NULL, 
	amount FLOAT NOT NULL, 
	source VARCHAR(60) NOT NULL, 
	captured_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(phone_id) REFERENCES phones (id) ON DELETE CASCADE
);

CREATE INDEX ix_prices_phone_id ON prices (phone_id);

CREATE TABLE specifications (
	id SERIAL NOT NULL, 
	phone_id INTEGER NOT NULL, 
	category VARCHAR(60) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	value TEXT NOT NULL, 
	position INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_spec_phone_position UNIQUE (phone_id, position), 
	FOREIGN KEY(phone_id) REFERENCES phones (id) ON DELETE CASCADE
);

CREATE INDEX ix_specifications_category ON specifications (category);

CREATE INDEX ix_specifications_phone_id ON specifications (phone_id);
