// Teste na placa do módulo auth (F4) com os vetores da seção 9 do CONTRATO.md.
//
// Roda no ESP32 (o mbedtls do núcleo não existe no PC). A partir de firmware/:
//
//   pio test -e demo -f test_auth --upload-port COM5 --test-port COM5
//
// A chave de teste é carregada por auth_begin_with_key_hex: não depende do
// include/secrets.h (que só precisa existir para compilar o auth).

#include <Arduino.h>
#include <string.h>
#include <unity.h>

#include "auth.h"

namespace {

// Chave da etiqueta a1b2c3d4e5f6 derivada da chave-mestra de teste (CONTRATO §9).
const char TEST_KEY_HEX[] = "d4c08c076e44144313962c8344e2629ea372ae885e07f354e1bd0cd8523fe573";

const char V1[] =
    "{\"produto\":{\"nome\":\"Dipirona 500 mg\",\"preco\":1490,\"descricao\":\"caixa com 20 "
    "comprimidos\",\"ean13\":\"7891234567895\"},\"promocao\":{\"preco\":1190,\"expira_em\":"
    "1795680000},\"versao\":\"5af98e6c\",\"seq\":42}";
const char V2[] =
    "{\"produto\":{\"nome\":\"Café Pilão 500 g\",\"preco\":2490,\"descricao\":\"torrado e "
    "moído\",\"ean13\":\"7896089012453\"},\"promocao\":null,\"versao\":\"5d527b68\",\"seq\":43}";
const char V3[] = "{\"produto\":null,\"promocao\":null,\"versao\":\"ebf5fe64\",\"seq\":44}";
const char V4[] =
    "{\"produto\":{\"nome\":\"Dipirona 500 mg\",\"preco\":990,\"descricao\":\"caixa com 20 "
    "comprimidos\",\"ean13\":\"7891234567895\"},\"promocao\":{\"preco\":1190,\"expira_em\":"
    "1795680000},\"versao\":\"5af98e6c\",\"seq\":42}";
const char V5[] =
    "{\"produto\":{\"nome\":\"Dipirona 500 mg\",\"preco\":1490,\"descricao\":\"caixa com 20 "
    "comprimidos\",\"ean13\":\"7891234567895\"},\"promocao\":{\"preco\":1190,\"expira_em\":"
    "1795680000},\"versao\":\"5af98e6c\",\"seq\":41}";

const char V1_HMAC[] = "9bb4c082b6209aa642ccf1652b2a5397";
const char V2_HMAC[] = "4f8f7929e872ef07e6a85fba574771ef";
const char V3_HMAC[] = "d9e4ebd4a9acd35286ddeef317dabc8a";
const char V5_HMAC[] = "829fa9736b1d7049bbe52de46f0c6dc3";
const char V6_HMAC[] = "2aa16b0291bb89d50167c2ab381e9421";

// Verifica `data` (texto inteiro, sem o '\0') e confere resultado e seq.
void check(const char* data, const char* hmac_hex, uint32_t last_seq, AuthResult expected,
           uint32_t expected_seq) {
    uint32_t seq = 0;
    const AuthResult got = auth_verify(data, strlen(data), hmac_hex, last_seq, &seq);
    TEST_ASSERT_EQUAL_STRING(auth_result_name(expected), auth_result_name(got));
    if (expected_seq != 0) {
        TEST_ASSERT_EQUAL_UINT32(expected_seq, seq);
    }
}

void check_result(const char* data, const char* hmac_hex, uint32_t last_seq,
                  AuthResult expected) {
    check(data, hmac_hex, last_seq, expected, 0);
}

}  // namespace

void setUp() {
    TEST_ASSERT_TRUE(auth_begin_with_key_hex(TEST_KEY_HEX));
}

void tearDown() {}

void test_v1_accepts_then_unchanged() {
    check(V1, V1_HMAC, 0, AuthResult::Ok, 42);
    check(V1, V1_HMAC, 42, AuthResult::Unchanged, 42);
}

void test_v2_accents() {
    check(V2, V2_HMAC, 42, AuthResult::Ok, 43);
}

void test_v3_no_product() {
    check(V3, V3_HMAC, 43, AuthResult::Ok, 44);
}

void test_v4_tampered_price() {
    check_result(V4, V1_HMAC, 0, AuthResult::BadHmac);
}

void test_v5_replay() {
    check(V5, V5_HMAC, 42, AuthResult::Replay, 41);
}

void test_v6_other_tag_key() {
    check_result(V1, V6_HMAC, 0, AuthResult::BadHmac);
}

void test_hmac_covers_exact_length() {
    // Um byte a menos (sem o '}' final) já muda o código
    uint32_t seq = 0;
    TEST_ASSERT_EQUAL_STRING(
        "bad-hmac", auth_result_name(auth_verify(V1, strlen(V1) - 1, V1_HMAC, 0, &seq)));
}

void test_malformed_hmac_hex() {
    check_result(V1, "9BB4C082B6209AA642CCF1652B2A5397", 0, AuthResult::Malformed);  // maiúsculas
    check_result(V1, "9bb4c082b6209aa642ccf1652b2a539", 0, AuthResult::Malformed);   // 31
    check_result(V1, "9bb4c082b6209aa642ccf1652b2a53970", 0, AuthResult::Malformed); // 33
    check_result(V1, "9bb4c082b6209aa642ccf1652b2a539g", 0, AuthResult::Malformed);  // não hex
    check_result(V1, "", 0, AuthResult::Malformed);
    check_result(V1, nullptr, 0, AuthResult::Malformed);
}

// Códigos válidos (chave de teste) sobre `dados` com `seq` ausente ou inválido,
// calculados no PC com hmac.new(chave, dados, sha256).hexdigest()[:32].
void test_malformed_seq() {
    check_result("{\"versao\":\"ebf5fe64\"}", "b42122d8b56558fae0f6ee07eb8dbd20", 0,
                 AuthResult::Malformed);  // ausente
    check_result("{\"versao\":\"ebf5fe64\",\"seq\":0}", "27b8ea3d9b74c5fd89869fd3579a50e4", 0,
                 AuthResult::Malformed);  // abaixo de 1
    check_result("{\"versao\":\"ebf5fe64\",\"seq\":2147483648}",
                 "c8487230ec774c709f44eff44e177f29", 0, AuthResult::Malformed);  // acima do máximo
    check_result("{\"versao\":\"ebf5fe64\",\"seq\":42.5}", "22e8fa99c319c7a8d675840f165bf301",
                 0, AuthResult::Malformed);  // não inteiro
    check_result("{\"versao\":\"ebf5fe64\",\"seq\":\"42\"}", "6e21f755bfb3e1c1bac91acc1f570db7",
                 0, AuthResult::Malformed);  // texto
    check_result("{\"seq\":42", "0ae7dd4429d0967e0ea18cd9772a5bce", 0,
                 AuthResult::Malformed);  // JSON incompleto
    check("{\"versao\":\"ebf5fe64\",\"seq\":2147483647}", "e3928007ecf2768587cef0b2a836dc16", 0,
          AuthResult::Ok, 2147483647);  // máximo do contrato
}

void test_invalid_key() {
    // 63 caracteres, caractere não hex e nulo: auth_begin falha e auth_verify recusa
    TEST_ASSERT_FALSE(auth_begin_with_key_hex(
        "d4c08c076e44144313962c8344e2629ea372ae885e07f354e1bd0cd8523fe57"));
    check_result(V1, V1_HMAC, 0, AuthResult::NoKey);
    TEST_ASSERT_FALSE(auth_begin_with_key_hex(
        "x4c08c076e44144313962c8344e2629ea372ae885e07f354e1bd0cd8523fe573"));
    check_result(V1, V1_HMAC, 0, AuthResult::NoKey);
    TEST_ASSERT_FALSE(auth_begin_with_key_hex(nullptr));
    check_result(V1, V1_HMAC, 0, AuthResult::NoKey);
}

void test_key_upper_case_accepted() {
    TEST_ASSERT_TRUE(auth_begin_with_key_hex(
        "D4C08C076E44144313962C8344E2629EA372AE885E07F354E1BD0CD8523FE573"));
    check(V1, V1_HMAC, 0, AuthResult::Ok, 42);
}

void setup() {
    // Dá tempo de o monitor do `pio test` abrir a porta depois do reset
    delay(2000);
    UNITY_BEGIN();
    RUN_TEST(test_v1_accepts_then_unchanged);
    RUN_TEST(test_v2_accents);
    RUN_TEST(test_v3_no_product);
    RUN_TEST(test_v4_tampered_price);
    RUN_TEST(test_v5_replay);
    RUN_TEST(test_v6_other_tag_key);
    RUN_TEST(test_hmac_covers_exact_length);
    RUN_TEST(test_malformed_hmac_hex);
    RUN_TEST(test_malformed_seq);
    RUN_TEST(test_invalid_key);
    RUN_TEST(test_key_upper_case_accepted);
    UNITY_END();
}

void loop() {}
