import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate } from 'k6/metrics';

// Кастомные метрики
const pdDetected = new Counter('pd_detected');
const errorRate = new Rate('error_rate');

export const options = {
  stages: [
    { duration: '30s', target: 100 },   // ramp-up до 100 VU
    { duration: '4m',  target: 100 },   // hold 100 VU
    { duration: '30s', target: 0 },     // ramp-down
  ],
  thresholds: {
    http_req_duration: ['p(99)<1000'],   // p99 < 1с
    http_req_failed:   ['rate<0.01'],    // ошибок < 1%
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

// Реалистичные тестовые данные
const NAMES = [
  'Иванов Иван Иванович',
  'Петрова Мария Сергеевна',
  'Козлов Алексей Дмитриевич',
  'Сидорова Елена Петровна',
  'Волков Дмитрий Андреевич',
];

const PHONES = [
  '+7 (999) 888-77-66',
  '+7 (916) 123-45-67',
  '8-800-555-35-35',
  '+7(495)7654321',
  '+79031234567',
];

const PASSPORTS = [
  '4510 123456',
  '4511 654321',
  '4600 987654',
];

const EMAILS = [
  'ivan@mail.ru',
  'maria@yandex.ru',
  'info@company.com',
];

const INNS = [
  '123456789012',
  '770123456789',
];

function randomItem(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

export default function () {
  const payload = `Клиент: ${randomItem(NAMES)}, паспорт ${randomItem(PASSPORTS)}, ` +
    `тел ${randomItem(PHONES)}, email ${randomItem(EMAILS)}, ИНН ${randomItem(INNS)}. ` +
    `Просьба оформить заявку на кредит.`;

  const uniqueId = `load-${__VU}-${__ITER}-${Date.now()}`;

  const res = http.post(`${BASE_URL}/process`, JSON.stringify({
    payload: payload,
    payload_id: uniqueId,
  }), {
    headers: { 'Content-Type': 'application/json' },
  });

  const ok = check(res, {
    'status 200': (r) => r.status === 200,
    'action is masked': (r) => {
      try {
        return JSON.parse(r.body).action === 'masked';
      } catch (e) {
        return false;
      }
    },
  });

  if (ok) {
    try {
      const data = JSON.parse(res.body);
      pdDetected.add(data.stats.pd_found || 0);
    } catch (e) {}
  }

  errorRate.add(!ok);
}
