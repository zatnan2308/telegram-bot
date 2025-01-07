-- create_all.sql

-- 1. Таблица users (основная для хранения пользователей)
CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    name VARCHAR(100),
    phone VARCHAR(20)
);

-- 2. Таблица user_state (хранение шагов сценария записи)
CREATE TABLE user_state (
    user_id BIGINT PRIMARY KEY,
    step VARCHAR(50),
    service_id INT,
    specialist_id INT,
    chosen_time VARCHAR(50),
    CONSTRAINT fk_user_state_user
      FOREIGN KEY (user_id) REFERENCES users (id)
      ON DELETE CASCADE
);

-- 3. Таблица services (список услуг)
CREATE TABLE services (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL
);

-- 4. Таблица specialists (список мастеров)
CREATE TABLE specialists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- 5. Таблица booking_times (слоты для записи, с флагом is_booked)
CREATE TABLE booking_times (
    id SERIAL PRIMARY KEY,
    specialist_id INT NOT NULL,
    service_id INT NOT NULL,
    slot_time TIMESTAMP NOT NULL,
    is_booked BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_bt_specialist 
      FOREIGN KEY (specialist_id) REFERENCES specialists (id)
      ON DELETE CASCADE,
    CONSTRAINT fk_bt_service
      FOREIGN KEY (service_id) REFERENCES services (id)
      ON DELETE CASCADE
);

-- 6. Таблица bookings (фактические записи)
CREATE TABLE bookings (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    service_id INT NOT NULL,
    specialist_id INT NOT NULL,
    date_time TIMESTAMP NOT NULL,
    date DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT fk_b_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_b_service FOREIGN KEY (service_id) REFERENCES services (id) ON DELETE CASCADE,
    CONSTRAINT fk_b_specialist FOREIGN KEY (specialist_id) REFERENCES specialists (id) ON DELETE CASCADE
);

-- (Опционально) Вставим тестовые услуги и специалистов:
INSERT INTO services (title) VALUES
('Косметический массаж'),
('Чистка лица'),
('Микродермабразия'),
('Химический пилинг'),
('Уход за кожей для мужчин'),
('Гидрафейшл'),
('Дермапланирование'),
('Микронидлинг');

INSERT INTO specialists (name) VALUES
('Анна Иванова'),
('Мария Петрова'),
('Светлана Смирнова'),
('Ольга Сидорова');

-- Если хотите, можете добавить тестовые слоты в booking_times:
-- Пример:
-- INSERT INTO booking_times (specialist_id, service_id, slot_time)
-- VALUES
--   (1, 2, '2025-01-08 10:00'),
--   (1, 2, '2025-01-08 12:00'),
--   (1, 2, '2025-01-08 14:00');
