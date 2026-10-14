#include "net.h"

#include <errno.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include <WiFi.h>
#include <esp_system.h>
#include <lwip/dns.h>
#include <lwip/sockets.h>
#include <lwip/tcpip.h>

#include "spt_log.h"
#include "spt_secrets.h"

namespace {
constexpr char TAG[] = "net";

// Relógio válido a partir de 01/01/2025 00:00 UTC (CONTRATO §8).
constexpr time_t CLOCK_VALID_FROM = 1735689600;

// Intervalo entre consultas de estado durante as esperas.
constexpr uint32_t POLL_MS = 50;

// Cliente SNTP próprio (RFC 4330) em vez de configTime(): o SNTP do lwIP
// sorteia até 5 s antes da primeira consulta e, se um pacote se perde, só
// tenta de novo após 15 s, o que estoura o prazo do ciclo.
constexpr char NTP_SERVER[] = "pool.ntp.org";
constexpr uint16_t NTP_PORT = 123;
constexpr size_t NTP_PACKET_SIZE = 48;
// Segundos entre 1900 (época do NTP) e 1970 (época Unix).
constexpr int64_t NTP_TO_UNIX_S = 2208988800LL;
// Reenvio da consulta (ou do DNS) quando a resposta não chega: UDP perde pacotes.
constexpr uint32_t NTP_RETRY_MS = 1000;
// Quanto net_sync_time_start() espera o DNS para já enviar a primeira consulta.
constexpr uint32_t DNS_WAIT_MS = 1000;

// Resultado do DNS, escrito pelo callback na thread do lwIP.
volatile bool dns_done = false;
volatile uint32_t dns_ip = 0;  // IPv4 em ordem de rede; 0 = falhou

int ntp_socket = -1;
uint32_t sntp_started_at = 0;
uint32_t dns_requested_at = 0;
bool request_sent = false;
uint32_t request_sent_at = 0;
// Transmit timestamp aleatório da consulta: o servidor o devolve como
// originate timestamp, e só a resposta a esta consulta é aceita.
uint8_t request_nonce[8];

void on_dns_found(const char* /*name*/, const ip_addr_t* addr, void* /*arg*/) {
    dns_ip = (addr != nullptr && IP_IS_V4(addr)) ? ip4_addr_get_u32(ip_2_ip4(addr)) : 0;
    dns_done = true;
}

// Roda na thread do lwIP (via tcpip_callback): dns_gethostbyname não é
// seguro fora dela, e assim a resolução não bloqueia o ciclo.
void dns_lookup(void* /*ctx*/) {
    ip_addr_t addr;
    const err_t err = dns_gethostbyname(NTP_SERVER, &addr, on_dns_found, nullptr);
    if (err == ERR_OK) {
        on_dns_found(nullptr, &addr, nullptr);
    } else if (err != ERR_INPROGRESS) {
        on_dns_found(nullptr, nullptr, nullptr);
    }
}

void start_dns() {
    dns_done = false;
    dns_ip = 0;
    dns_requested_at = millis();
    if (tcpip_callback(dns_lookup, nullptr) != ERR_OK) {
        dns_done = true;
    }
}

uint32_t read_be32(const uint8_t* p) {
    return (static_cast<uint32_t>(p[0]) << 24) | (static_cast<uint32_t>(p[1]) << 16) |
           (static_cast<uint32_t>(p[2]) << 8) | static_cast<uint32_t>(p[3]);
}

void send_request() {
    uint8_t packet[NTP_PACKET_SIZE] = {};
    packet[0] = 0x23;  // LI 0, versão 4, modo 3 (cliente)
    const uint32_t nonce_hi = esp_random();
    const uint32_t nonce_lo = esp_random();
    memcpy(request_nonce, &nonce_hi, sizeof(nonce_hi));
    memcpy(request_nonce + sizeof(nonce_hi), &nonce_lo, sizeof(nonce_lo));
    memcpy(packet + 40, request_nonce, sizeof(request_nonce));

    sockaddr_in to = {};
    to.sin_family = AF_INET;
    to.sin_port = htons(NTP_PORT);
    to.sin_addr.s_addr = dns_ip;
    request_sent_at = millis();
    request_sent = sendto(ntp_socket, packet, sizeof(packet), 0,
                          reinterpret_cast<sockaddr*>(&to), sizeof(to)) ==
                   static_cast<int>(sizeof(packet));
    if (!request_sent) {
        SPT_LOGD(TAG, "falha ao enviar a consulta SNTP (errno %d)", errno);
    }
}

// Lê as respostas pendentes; true se uma válida acertou o relógio.
bool read_reply() {
    uint8_t packet[NTP_PACKET_SIZE];
    while (true) {
        const int len = recvfrom(ntp_socket, packet, sizeof(packet), MSG_DONTWAIT, nullptr, nullptr);
        if (len < 0) {
            return false;
        }
        if (len < static_cast<int>(NTP_PACKET_SIZE)) {
            SPT_LOGD(TAG, "resposta SNTP curta descartada (%d bytes)", len);
            continue;
        }
        const uint8_t leap = packet[0] >> 6;
        const uint8_t mode = packet[0] & 0x07;
        const uint8_t stratum = packet[1];
        const uint32_t ntp_s = read_be32(packet + 40);
        // Descarta respostas de servidor não sincronizado, "kiss-o'-death"
        // (stratum 0) e as que não ecoam a consulta atual
        if (mode != 4 || leap == 3 || stratum == 0 || stratum > 15 || ntp_s == 0 ||
            memcmp(packet + 24, request_nonce, sizeof(request_nonce)) != 0) {
            SPT_LOGD(TAG, "resposta SNTP descartada (modo %u, stratum %u)", mode, stratum);
            continue;
        }

        // Era NTP 1 a partir de 2036: valores com o bit alto zerado já são da era seguinte
        int64_t unix_s = static_cast<int64_t>(ntp_s) - NTP_TO_UNIX_S;
        if (ntp_s < 0x80000000u) {
            unix_s += 0x100000000LL;
        }
        // A resposta pode ter esperado no socket enquanto o MQTT trabalhava, e o
        // instante de chegada não é conhecido: soma-se todo o tempo desde o envio,
        // o que adianta o relógio em no máximo meia ida e volta da rede
        const uint32_t since_sent_ms = millis() - request_sent_at;
        uint64_t us = (static_cast<uint64_t>(read_be32(packet + 44)) * 1000000ULL) >> 32;
        us += static_cast<uint64_t>(since_sent_ms) * 1000ULL;

        timeval tv = {};
        tv.tv_sec = static_cast<time_t>(unix_s + static_cast<int64_t>(us / 1000000ULL));
        tv.tv_usec = static_cast<suseconds_t>(us % 1000000ULL);
        settimeofday(&tv, nullptr);
        SPT_LOGD(TAG, "SNTP: servidor %s, stratum %u, resposta lida %lu ms após o envio",
                 IPAddress(dns_ip).toString().c_str(), stratum,
                 static_cast<unsigned long>(since_sent_ms));
        return true;
    }
}

// Um passo do cliente: lê a resposta e, se preciso, refaz o DNS ou reenvia a consulta.
bool sntp_step() {
    if (request_sent && read_reply()) {
        return true;
    }
    const uint32_t now = millis();
    if (dns_done && dns_ip == 0 && now - dns_requested_at >= NTP_RETRY_MS) {
        start_dns();
    } else if (dns_done && dns_ip != 0 && (!request_sent || now - request_sent_at >= NTP_RETRY_MS)) {
        send_request();
    }
    return false;
}

void sntp_stop() {
    if (ntp_socket >= 0) {
        close(ntp_socket);
        ntp_socket = -1;
    }
    sntp_started_at = 0;
    request_sent = false;
}
}  // namespace

bool net_connect(uint32_t timeout_ms) {
    const uint32_t start = millis();
    // Não gravar as credenciais na flash a cada ciclo
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start >= timeout_ms) {
            SPT_LOGW(TAG, "Wi-Fi não conectou em %lu ms (status %d)",
                     static_cast<unsigned long>(timeout_ms), static_cast<int>(WiFi.status()));
            WiFi.disconnect(true);
            WiFi.mode(WIFI_OFF);
            return false;
        }
        delay(POLL_MS);
    }

    SPT_LOGI(TAG, "Wi-Fi conectado em %lu ms, IP %s, RSSI %d dBm",
             static_cast<unsigned long>(millis() - start),
             WiFi.localIP().toString().c_str(), static_cast<int>(WiFi.RSSI()));
    return true;
}

void net_sync_time_start() {
    if (sntp_started_at != 0) {
        return;
    }
    sntp_started_at = millis() | 1;  // 0 significa "não disparado"
    ntp_socket = socket(AF_INET, SOCK_DGRAM, 0);
    if (ntp_socket < 0) {
        SPT_LOGE(TAG, "falha ao criar o socket SNTP (errno %d)", errno);
        return;
    }
    start_dns();
    // O DNS costuma levar poucas centenas de ms; com o IP em mãos, a consulta
    // já sai agora e a resposta espera no socket enquanto o MQTT trabalha
    while (!dns_done && millis() - sntp_started_at < DNS_WAIT_MS) {
        delay(10);
    }
    sntp_step();
}

bool net_sync_time(uint32_t timeout_ms) {
    net_sync_time_start();
    const uint32_t start = millis();
    bool synced = ntp_socket >= 0;

    while (synced && !sntp_step()) {
        if (millis() - start >= timeout_ms) {
            synced = false;
            break;
        }
        delay(POLL_MS);
    }

    const uint32_t elapsed = millis() - sntp_started_at;
    const bool dns_failed = dns_done && dns_ip == 0;
    sntp_stop();

    const int64_t now = net_now_utc();
    if (!synced) {
        SPT_LOGW(TAG, "SNTP sem resposta%s em %lu ms; relógio %s",
                 dns_failed ? " (DNS falhou)" : "", static_cast<unsigned long>(elapsed),
                 now != 0 ? "mantido do ciclo anterior" : "inválido");
        return false;
    }
    if (now == 0) {
        SPT_LOGW(TAG, "SNTP respondeu, mas o instante é anterior a 2025");
        return false;
    }
    SPT_LOGI(TAG, "relógio sincronizado %lu ms após o disparo: %lld UTC",
             static_cast<unsigned long>(elapsed), static_cast<long long>(now));
    return true;
}

int64_t net_now_utc() {
    const time_t now = time(nullptr);
    return now >= CLOCK_VALID_FROM ? static_cast<int64_t>(now) : 0;
}

int16_t net_rssi_dbm() {
    if (WiFi.status() != WL_CONNECTED) {
        return 0;
    }
    return static_cast<int16_t>(WiFi.RSSI());
}

void net_disconnect() {
    sntp_stop();
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
}
