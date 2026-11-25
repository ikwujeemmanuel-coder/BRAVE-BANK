/** Progressive 4-Step BraveBank Registration Controller (Details -> Verify Email OTP -> Set 4-Digit PIN -> Success). */

import { apiRequest } from "./api.js";
import {
  appState,
  escapeHtml,
  isValidNigerianPhoneClient,
  maskEmailClient,
  validatePasswordClient,
} from "./state.js";
import { openTermsModal, showToast, withButtonLoading } from "./ui.js";

let cooldownTimer = null;
let autoRedirectTimer = null;
let isStartingReg = false;
let isVerifyingEmail = false;
let isSettingPin = false;

function formatCountdown(seconds) {
  const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");
  return `(${mins}:${secs})`;
}

export function setBannerError(el, message) {
  if (!el) return;
  if (message) {
    el.textContent = message;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

export function setFieldError(inputId, errorId, message) {
  const inputEl = document.getElementById(inputId);
  const errEl = document.getElementById(errorId);
  if (inputEl) {
    inputEl.classList.toggle("input-invalid", Boolean(message));
  }
  if (errEl) {
    if (message) {
      errEl.textContent = message;
      errEl.classList.remove("hidden");
    } else {
      errEl.textContent = "";
      errEl.classList.add("hidden");
    }
  }
}

export function clearFormErrors(pairs, bannerEl) {
  pairs.forEach(([inputId, errId]) => setFieldError(inputId, errId, ""));
  setBannerError(bannerEl, "");
}

function replayStepAnimation(el) {
  if (!el) return;
  el.classList.remove("progressive-step");
  void el.offsetWidth;
  el.classList.add("progressive-step");
}

export function initRegistrationFlow({ showAuthScreen, enterAuthenticatedShell }) {
  const registerForm = document.getElementById("register-form");
  const otpForm = document.getElementById("otp-form");
  const pinSetupForm = document.getElementById("pin-setup-form");
  const regSuccessPanel = document.getElementById("reg-success-panel");

  const regFormError = document.getElementById("reg-form-error");
  const otpFormError = document.getElementById("otp-form-error");
  const pinFormError = document.getElementById("pin-form-error");
  const devOtpBox = document.getElementById("dev-otp-box");

  const otpTargetEmailEl = document.getElementById("otp-target-email");
  const otpBoxes = Array.from(document.querySelectorAll(".otp-box"));
  const otpHiddenCode = document.getElementById("otp-code");
  const otpEmailHidden = document.getElementById("otp-email");
  const otpCountdownEl = document.getElementById("otp-countdown");
  const resendBtn = document.getElementById("resend-otp-btn");

  function startOtpCooldown(seconds = 60) {
    if (cooldownTimer) clearInterval(cooldownTimer);
    let remaining = Math.max(0, Number(seconds) || 60);
    if (remaining === 0) {
      resendBtn.disabled = false;
      otpCountdownEl.textContent = "";
      return;
    }
    resendBtn.disabled = true;
    otpCountdownEl.textContent = formatCountdown(remaining);

    cooldownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(cooldownTimer);
        cooldownTimer = null;
        resendBtn.disabled = false;
        otpCountdownEl.textContent = "(00:00)";
      } else {
        otpCountdownEl.textContent = formatCountdown(remaining);
      }
    }, 1000);
  }

  function syncOtpHiddenValue() {
    otpHiddenCode.value = otpBoxes.map((box) => box.value.trim()).join("");
  }

  otpBoxes.forEach((box, idx) => {
    box.addEventListener("input", (e) => {
      const digits = e.target.value.replace(/\D/g, "");
      if (digits.length > 1) {
        digits.split("").slice(0, 6).forEach((ch, offset) => {
          if (otpBoxes[idx + offset]) otpBoxes[idx + offset].value = ch;
        });
        const next = otpBoxes[Math.min(5, idx + digits.length)];
        if (next) next.focus();
      } else {
        e.target.value = digits;
        if (digits && otpBoxes[idx + 1]) otpBoxes[idx + 1].focus();
      }
      syncOtpHiddenValue();
      setBannerError(otpFormError, "");
    });

    box.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !box.value && otpBoxes[idx - 1]) {
        otpBoxes[idx - 1].focus();
      }
    });
  });

  [
    ["reg-first-name", "err-reg-first-name"],
    ["reg-surname", "err-reg-surname"],
    ["reg-phone", "err-reg-phone"],
    ["reg-email", "err-reg-email"],
    ["reg-password", "err-reg-password"],
    ["reg-confirm-password", "err-reg-confirm-password"],
    ["setup-pin", "err-setup-pin"],
    ["setup-confirm-pin", "err-setup-confirm-pin"],
  ].forEach(([inputId, errId]) => {
    const el = document.getElementById(inputId);
    if (el) {
      el.addEventListener("input", () => {
        setFieldError(inputId, errId, "");
        setBannerError(regFormError, "");
        setBannerError(pinFormError, "");
      });
    }
  });

  function showStep(stepName) {
    registerForm.classList.toggle("hidden", stepName !== "details");
    otpForm.classList.toggle("hidden", stepName !== "verify_email");
    pinSetupForm.classList.toggle("hidden", stepName !== "set_pin");
    regSuccessPanel.classList.toggle("hidden", stepName !== "success");

    if (stepName === "details") replayStepAnimation(registerForm);
    if (stepName === "verify_email") replayStepAnimation(otpForm);
    if (stepName === "set_pin") replayStepAnimation(pinSetupForm);
    if (stepName === "success") replayStepAnimation(regSuccessPanel);
  }

  function enterEmailOtpStep(info) {
    showAuthScreen("register", false);
    showStep("verify_email");
    setBannerError(otpFormError, "");

    const emailVal = info.email || "";
    otpEmailHidden.value = emailVal;
    otpTargetEmailEl.textContent = info.masked_email || maskEmailClient(emailVal) || "your email";

    if (info.dev_otp) {
      devOtpBox.textContent = `Development Email OTP: ${info.dev_otp}`;
      devOtpBox.classList.remove("hidden");
    } else {
      devOtpBox.classList.add("hidden");
      devOtpBox.textContent = "";
    }

    otpBoxes.forEach((b) => (b.value = ""));
    syncOtpHiddenValue();
    if (otpBoxes[0]) otpBoxes[0].focus();
    startOtpCooldown(info.resend_cooldown_seconds || 60);
  }

  function enterSetPinStep(info) {
    showAuthScreen("register", false);
    showStep("set_pin");
    setBannerError(pinFormError, "");
    document.getElementById("setup-pin").value = "";
    document.getElementById("setup-confirm-pin").value = "";
    document.getElementById("setup-pin").focus();
  }

  function enterSuccessStep(user) {
    if (autoRedirectTimer) {
      clearTimeout(autoRedirectTimer);
      autoRedirectTimer = null;
    }
    showAuthScreen("register", false);
    showStep("success");

    document.getElementById("reg-success-summary").textContent =
      `Welcome, ${user.first_name} ${user.surname}. Your BraveBank NGN account has been created.`;
    document.getElementById("reg-success-details").innerHTML = `
      <div class="summary-kv-row"><span class="summary-kv-left">Account Holder</span><strong class="summary-kv-val">${escapeHtml(user.first_name)} ${escapeHtml(user.surname)}</strong></div>
      <div class="summary-kv-row"><span class="summary-kv-left">BraveBank Account</span><strong class="summary-kv-val">${escapeHtml(user.account_number || "—")}</strong></div>
      <div class="summary-kv-row"><span class="summary-kv-left">Verified Email</span><strong class="summary-kv-val">${escapeHtml(user.email || "—")}</strong></div>
      <div class="summary-kv-row"><span class="summary-kv-left">Phone Number</span><strong class="summary-kv-val">${escapeHtml(user.phone_number)}</strong></div>
      <div class="summary-kv-row"><span class="summary-kv-left">Transaction PIN</span><strong class="summary-kv-val">4-Digit PIN Active</strong></div>
    `;
  }

  // Navigation buttons inside registration steps
  document.getElementById("reg-back-btn").addEventListener("click", () => showAuthScreen("welcome"));
  document.getElementById("reg-have-account-btn").addEventListener("click", () => showAuthScreen("login"));
  document.getElementById("open-terms-btn").addEventListener("click", openTermsModal);

  document.getElementById("otp-back-btn").addEventListener("click", () => {
    appState.pendingRegistration = null;
    showStep("details");
  });

  document.getElementById("pin-back-btn").addEventListener("click", () => {
    appState.pendingRegistration = null;
    showStep("details");
  });

  document.getElementById("enter-dashboard-btn").addEventListener("click", async () => {
    if (autoRedirectTimer) {
      clearTimeout(autoRedirectTimer);
      autoRedirectTimer = null;
    }
    appState.pendingRegistration = null;
    await enterAuthenticatedShell();
  });

  // STEP 1: Submit Personal Details -> Dispatch Email OTP
  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isStartingReg) return;

    clearFormErrors(
      [
        ["reg-first-name", "err-reg-first-name"],
        ["reg-surname", "err-reg-surname"],
        ["reg-phone", "err-reg-phone"],
        ["reg-email", "err-reg-email"],
        ["reg-password", "err-reg-password"],
        ["reg-confirm-password", "err-reg-confirm-password"],
      ],
      regFormError
    );

    const firstName = document.getElementById("reg-first-name").value.trim();
    const surname = document.getElementById("reg-surname").value.trim();
    const phone = document.getElementById("reg-phone").value.trim();
    const emailVal = document.getElementById("reg-email").value.trim();
    const pw = document.getElementById("reg-password").value;
    const confirmPw = document.getElementById("reg-confirm-password").value;

    let hasErrors = false;
    if (firstName.length < 2) {
      setFieldError("reg-first-name", "err-reg-first-name", "First name must be at least 2 characters.");
      hasErrors = true;
    }
    if (surname.length < 2) {
      setFieldError("reg-surname", "err-reg-surname", "Surname must be at least 2 characters.");
      hasErrors = true;
    }
    if (!isValidNigerianPhoneClient(phone)) {
      setFieldError("reg-phone", "err-reg-phone", "Enter a valid Nigerian phone number (e.g. 08012345678).");
      hasErrors = true;
    }
    if (!emailVal || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailVal)) {
      setFieldError("reg-email", "err-reg-email", "A valid email address is required for verification.");
      hasErrors = true;
    }
    const pwErr = validatePasswordClient(pw);
    if (pwErr) {
      setFieldError("reg-password", "err-reg-password", pwErr);
      hasErrors = true;
    }
    if (pw !== confirmPw) {
      setFieldError("reg-confirm-password", "err-reg-confirm-password", "Passwords do not match.");
      hasErrors = true;
    }
    if (hasErrors) return;

    isStartingReg = true;
    const btn = document.getElementById("reg-submit-btn");
    try {
      await withButtonLoading(btn, "Sending Email Code...", async () => {
        try {
          const res = await apiRequest("/api/auth/register/start", {
            method: "POST",
            body: JSON.stringify({
              first_name: firstName,
              surname,
              phone_number: phone,
              email: emailVal,
              password: pw,
              confirm_password: confirmPw,
            }),
          });
          appState.pendingRegistration = {
            step: "verify_email",
            email: res.email,
            masked_email: res.masked_email,
            phone_number: res.phone_number,
            resend_cooldown_seconds: res.resend_cooldown_seconds || 60,
            dev_otp: res.dev_otp || null,
          };
          showToast(res.message, "success");
          enterEmailOtpStep(appState.pendingRegistration);
        } catch (err) {
          setBannerError(regFormError, err.message);
          showToast(err.message, "error");
        }
      });
    } finally {
      isStartingReg = false;
    }
  });

  // STEP 2: Verify 6-Digit Email OTP
  otpForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isVerifyingEmail) return;

    syncOtpHiddenValue();
    const code = otpHiddenCode.value;
    if (!/^\d{6}$/.test(code)) {
      setBannerError(otpFormError, "Enter all 6 digits sent to your email address.");
      return;
    }

    isVerifyingEmail = true;
    const btn = document.getElementById("otp-verify-btn");
    try {
      await withButtonLoading(btn, "Verifying Email...", async () => {
        try {
          const res = await apiRequest("/api/auth/register/verify-email", {
            method: "POST",
            body: JSON.stringify({
              email: otpEmailHidden.value.trim(),
              code,
            }),
          });
          appState.pendingRegistration = {
            step: "set_pin",
            email: res.email,
            masked_email: res.masked_email,
            registration_token: res.registration_token,
          };
          showToast(res.message, "success");
          enterSetPinStep(appState.pendingRegistration);
        } catch (err) {
          setBannerError(otpFormError, err.message);
          showToast(err.message, "error");
        }
      });
    } finally {
      isVerifyingEmail = false;
    }
  });

  // Resend Email OTP
  resendBtn.addEventListener("click", async () => {
    const email = otpEmailHidden.value.trim();
    if (!email) {
      setBannerError(otpFormError, "Email address missing. Go back and enter your details.");
      return;
    }
    try {
      const res = await apiRequest("/api/auth/register/resend-email-otp", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      if (res.dev_otp) {
        devOtpBox.textContent = `Development Email OTP: ${res.dev_otp}`;
        devOtpBox.classList.remove("hidden");
      }
      startOtpCooldown(res.resend_cooldown_seconds || 60);
      setBannerError(otpFormError, "");
      showToast("A new 6-digit verification code was sent to your email.", "success");
    } catch (err) {
      setBannerError(otpFormError, err.message);
      showToast(err.message, "error");
    }
  });

  // STEP 3: Create 4-Digit Transaction PIN -> Step 4 Success
  pinSetupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isSettingPin) return;

    clearFormErrors(
      [
        ["setup-pin", "err-setup-pin"],
        ["setup-confirm-pin", "err-setup-confirm-pin"],
      ],
      pinFormError
    );

    const pin = document.getElementById("setup-pin").value.trim();
    const confirmPin = document.getElementById("setup-confirm-pin").value.trim();
    let invalid = false;

    if (!/^\d{4}$/.test(pin)) {
      setFieldError("setup-pin", "err-setup-pin", "Transaction PIN must be exactly 4 numeric digits.");
      invalid = true;
    }
    if (pin !== confirmPin) {
      setFieldError("setup-confirm-pin", "err-setup-confirm-pin", "Transaction PINs do not match.");
      invalid = true;
    }
    if (invalid) return;

    const regToken = appState.pendingRegistration?.registration_token;
    if (!regToken) {
      setBannerError(pinFormError, "Registration session expired. Please verify your email again.");
      return;
    }

    isSettingPin = true;
    const btn = document.getElementById("setup-pin-submit-btn");
    try {
      await withButtonLoading(btn, "Creating Account...", async () => {
        try {
          const data = await apiRequest("/api/auth/register/set-pin", {
            method: "POST",
            body: JSON.stringify({
              registration_token: regToken,
              pin,
              confirm_pin: confirmPin,
            }),
          });
          appState.accessToken = data.access_token || null;
          appState.csrfToken = data.csrf_token || null;
          appState.user = data.user;
          appState.pendingRegistration = { step: "success", user: data.user };
          showToast("BraveBank account created successfully!", "success");
          enterSuccessStep(data.user);
        } catch (err) {
          setBannerError(pinFormError, err.message);
          showToast(err.message, "error");
        }
      });
    } finally {
      isSettingPin = false;
    }
  });

  return {
    showCurrentStep: () => {
      const pending = appState.pendingRegistration;
      if (pending && pending.step === "verify_email") {
        enterEmailOtpStep(pending);
      } else if (pending && pending.step === "set_pin") {
        enterSetPinStep(pending);
      } else if (pending && pending.step === "success" && pending.user) {
        enterSuccessStep(pending.user);
      } else {
        showStep("details");
      }
    },
    resumeFromLogin: (resumePayload) => {
      appState.pendingRegistration = resumePayload;
      if (resumePayload.step === "verify_email") {
        enterEmailOtpStep(resumePayload);
      } else if (resumePayload.step === "set_pin") {
        enterSetPinStep(resumePayload);
      }
    },
  };
}
