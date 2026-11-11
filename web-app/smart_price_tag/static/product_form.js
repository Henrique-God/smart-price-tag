"use strict";

const priceInput = document.getElementById("price");
priceInput?.addEventListener("input", () => {
  const cents = Math.round(Number(priceInput.value.replace(",", ".")) * 100);
  priceInput.setCustomValidity(
    Number.isFinite(cents) && cents >= 1 && cents <= 99999
      ? "" : "Informe um preço de R$ 0,01 a R$ 999,99."
  );
});

document.getElementById("generate-ean13")?.addEventListener("click", () => {
  const random = crypto.getRandomValues(new Uint32Array(12));
  const digits = Array.from(random, value => value % 10);
  const sum = digits.reduce((total, digit, index) => total + digit * (index % 2 === 0 ? 1 : 3), 0);
  const input = document.getElementById("ean13");
  input.value = digits.join("") + ((10 - sum % 10) % 10);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
});
