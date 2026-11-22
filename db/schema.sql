-- Generated from billing-api/app/models.py (PostgreSQL dialect).
-- Tables are created automatically by `python -m app.seed`.

CREATE TABLE subscribers (
	subscriber_no VARCHAR(20) NOT NULL, 
	full_name VARCHAR(100) NOT NULL, 
	plan_name VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (subscriber_no)
);

CREATE TABLE app_users (
	id SERIAL NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	password_hash VARCHAR(200) NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	subscriber_no VARCHAR(20), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_user_role CHECK (role in ('SUBSCRIBER','ADMIN')), 
	UNIQUE (username), 
	FOREIGN KEY(subscriber_no) REFERENCES subscribers (subscriber_no)
);

CREATE TABLE bills (
	id SERIAL NOT NULL, 
	subscriber_no VARCHAR(20) NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	phone_minutes INTEGER NOT NULL, 
	internet_mb INTEGER NOT NULL, 
	phone_charge NUMERIC(10, 2) NOT NULL, 
	internet_charge NUMERIC(10, 2) NOT NULL, 
	total NUMERIC(10, 2) NOT NULL, 
	paid_amount NUMERIC(10, 2) NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	calculated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_bill_period UNIQUE (subscriber_no, year, month), 
	CONSTRAINT ck_bill_status CHECK (status in ('UNPAID','PARTIALLY_PAID','PAID')), 
	CONSTRAINT ck_bill_paid CHECK (paid_amount >= 0), 
	FOREIGN KEY(subscriber_no) REFERENCES subscribers (subscriber_no)
);

CREATE TABLE usage_records (
	id SERIAL NOT NULL, 
	subscriber_no VARCHAR(20) NOT NULL, 
	year INTEGER NOT NULL, 
	month INTEGER NOT NULL, 
	usage_type VARCHAR(10) NOT NULL, 
	quantity INTEGER NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_usage_type CHECK (usage_type in ('PHONE','INTERNET')), 
	CONSTRAINT ck_usage_qty CHECK (quantity > 0), 
	CONSTRAINT ck_usage_month CHECK (month between 1 and 12), 
	FOREIGN KEY(subscriber_no) REFERENCES subscribers (subscriber_no)
);

CREATE INDEX ix_usage_records_subscriber_no ON usage_records (subscriber_no);

CREATE TABLE payments (
	id SERIAL NOT NULL, 
	transaction_id VARCHAR(64) NOT NULL, 
	bill_id INTEGER NOT NULL, 
	amount NUMERIC(10, 2) NOT NULL, 
	paid_by VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_payment_amount CHECK (amount > 0), 
	UNIQUE (transaction_id), 
	FOREIGN KEY(bill_id) REFERENCES bills (id)
);

CREATE INDEX ix_payments_bill_id ON payments (bill_id);
