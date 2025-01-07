-- create_all.sql

-- 1. Таблица users (основная для хранения пользователей)
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    name VARCHAR(100),
    phone VARCHAR(20)
);

-- 2. Таблица user_state (хранение шагов сценария записи)
CREATE TABLE IF NOT EXISTS user_state (
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
CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL
);

-- 4. Таблица specialists (список мастеров)
CREATE TABLE IF NOT EXISTS specialists (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL
);

-- 5. Таблица specialist_services (связь специалистов с услугами)
CREATE TABLE IF NOT EXISTS specialist_services (
    specialist_id INT NOT NULL,
    service_id INT NOT NULL,
    PRIMARY KEY (specialist_id, service_id),
    FOREIGN KEY (specialist_id) REFERENCES specialists(id) ON DELETE CASCADE,
    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
);

-- 6. Таблица booking_times (слоты для записи, с флагом is_booked)
CREATE TABLE IF NOT EXISTS booking_times (
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

-- 7. Таблица bookings (фактические записи)
CREATE TABLE IF NOT EXISTS bookings (
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

-- 8. Вставка тестовых услуг
INSERT INTO services (title) VALUES
('Косметический массаж'),
('Чистка лица'),
('Микродермабразия'),
('Химический пилинг'),
('Уход за кожей для мужчин'),
('Гидрафейшл'),
('Дермапланирование'),
('Микронидлинг');

-- 9. Вставка тестовых специалистов
INSERT INTO specialists (name) VALUES
('Анна Иванова'),
('Мария Петрова'),
('Светлана Смирнова'),
('Ольга Сидорова');

-- 10. Связывание специалистов с услугами
INSERT INTO specialist_services (specialist_id, service_id) VALUES
(1, 1), -- Анна Иванова предлагает Косметический массаж
(1, 2), -- Анна Иванова предлагает Чистка лица
(2, 2), -- Мария Петрова предлагает Чистка лица
(2, 3), -- Мария Петрова предлагает Микродермабразия
(3, 4), -- Светлана Смирнова предлагает Химический пилинг
(3, 5), -- Светлана Смирнова предлагает Уход за кожей для мужчин
(4, 6), -- Ольга Сидорова предлагает Гидрафейшл
(4, 7), -- Ольга Сидорова предлагает Дермапланирование
(4, 8); -- Ольга Сидорова предлагает Микронидлинг

-- 11. Вставка тестовых слотов в booking_times
-- Предположим, что каждый слот представляет 1 час и уже не забронирован
INSERT INTO booking_times (specialist_id, service_id, slot_time) VALUES
(1, 1, '2025-01-08 10:00'),
(1, 1, '2025-01-08 11:00'),
(1, 2, '2025-01-08 12:00'),
(2, 2, '2025-01-08 10:00'),
(2, 3, '2025-01-08 11:00'),
(3, 4, '2025-01-08 10:00'),
(3, 5, '2025-01-08 11:00'),
(4, 6, '2025-01-08 10:00'),
(4, 7, '2025-01-08 11:00'),
(4, 8, '2025-01-08 12:00');
