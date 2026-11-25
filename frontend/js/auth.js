/** Welcome, Login, Forgot Password, and password visibility authentication controller. */

import { apiRequest } from "./api.js";
import { icon } from "./icons.js";
import {
  clearFormErrors,
  initRegistrationFlow,
  setBannerError,
  setFieldError,
} from "./registration.js";
import {
  appState,
  isValidNigerianPhoneClient,
  validatePasswordClient,
} from "./state.js";
import { showToast, withButtonLoading } from "./ui.js";

let isLoggingIn = false;

export function initAuthFlow({ enterAuthenticatedShell }) {
  const welcomeView = document.getElementById("welcome-view");
  const loginView = document.getElementById("login-view");
  const registerView = document.getElementById("register-view");
  const resetView = document.getElementById("reset-view");

  const loginForm = document.getElementById("login-form");
  const loginFormError = document.getElementById("login-form-error");
  const resetDevOtpBox = document.getElementById("reset-dev-otp-box");

  let regController = null;

  function showAuthScreen(screen, syncRegStep = true) {
    welcomeView.classList.toggle("hidden", screen !== "welcome");
    loginView.classList.toggle("hidden", screen !== "login");
    registerView.classList.toggle("hidden", screen !== "register");
    resetView.classList.toggle("hidden", screen !== "reset");

    if (screen === "register" && syncRegStep && regController) {
      regController.showCurrentStep();
    }
  }

  regController = initRegistrationFlow({ showAuthScreen, enterAuthenticatedShell });

  // Crisp SVG eye toggles for password inputs
  document.querySelectorAll("[data-toggle-pw]").forEach((btn) => {
    btn.innerHTML = icon("eye", 18);
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.togglePw);
      if (!input) return;
      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      btn.innerHTML = isPassword ? icon("eyeOff", 18) : icon("eye", 18);
    });
  });

  [
    ["login-phone", "err-login-phone"],
    ["login-password", "err-login-password"],
  ].forEach(([inputId, errId]) => {
    const el = document.getElementById(inputId);
    if (el) {
      el.addEventListener("input", () => {
        setFieldError(inputId, errId, "");
        setBannerError(loginFormError, "");
      });
    }
  });

  // Welcome & Auth navigation
  document.getElementById("welcome-login-btn").addEventListener("click", () => {
    showAuthScreen("login");
    document.getElementById("login-phone").focus();
  });
  document.getElementById("welcome-create-btn").addEventListener("click", () => {
    appState.pendingRegistration = null;
    showAuthScreen("register");
    document.getElementById("reg-first-name").focus();
  });
  document.getElementById("login-back-btn").addEventListener("click", () => showAuthScreen("welcome"));
  document.getElementById("switch-to-register-btn").addEventListener("click", () => {
    appState.pendingRegistration = null;
    showAuthScreen("register");
    document.getElementById("reg-first-name").focus();
  });
  document.getElementById("open-reset-btn").addEventListener("click", () => showAuthScreen("reset"));
  document.getElementById("back-to-login-btn").addEventListener("click", () => showAuthScreen("login"));

  // Login submission
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (isLoggingIn) return;

    clearFormErrors(
      [
        ["login-phone", "err-login-phone"],
        ["login-password", "err-login-password"],
      ],
      loginFormError
    );

    const phone = document.getElementById("login-phone").value.trim();
    const password = document.getElementById("login-password").value;
    let valid = true;

    if (!isValidNigerianPhoneClient(phone)) {
      setFieldError(
        "login-phone",
        "err-login-phone",
        "Enter a valid Nigerian phone number (e.g. 08012345678 or +2348012345678)."
      );
      valid = false;
    }
    if (!password) {
      setFieldError("login-password", "err-login-password", "Password is required.");
      valid = false;
    }
    if (!valid) return;

    isLoggingIn = true;
    const btn = document.getElementById("login-submit-btn");
    try {
      await withButtonLoading(btn, "Logging in...", async () => {
        try {
          const data = await apiRequest("/api/auth/login", {
            method: "POST",
            body: JSON.stringify({ phone_number: phone, password }),
          });
          appState.accessToken = data.access_token || null;
          appState.user = data.user;
          appState.pendingRegistration = null;
          await enterAuthenticatedShell();
        } catch (err) {
          setBannerError(loginFormError, err.message);
          showToast(err.message, "error");

          // If incomplete registration, authenticate via /register/resume cleanly
          if (err.status === 403) {
            try {
              const resumeRes = await apiRequest("/api/auth/register/resume", {
                method: "POST",
                body: JSON.stringify({ phone_number: phone, password }),
              });
              if (resumeRes.step === "verify_email" || resumeRes.step === "set_pin") {
                regController.resumeFromLogin(resumeRes);
              }
            } catch {
              // Keep login error banner visible if resume fails
            }
          }
        }
      });
    } finally {
      isLoggingIn = false;
    }
  });

  // Password Reset
  document.getElementById("reset-request-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await apiRequest("/api/auth/password/reset-request", {
        method: "POST",
        body: JSON.stringify({ phone_number: document.getElementById("reset-phone").value }),
      });
      if (res.dev_otp) {
        resetDevOtpBox.textContent = `Development Reset OTP: ${res.dev_otp}`;
        resetDevOtpBox.classList.remove("hidden");
      }
      showToast(res.message, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("reset-confirm-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const pw = document.getElementById("reset-new-pw").value;
    const confirmPw = document.getElementById("reset-confirm-pw").value;
    const pwErr = validatePasswordClient(pw, confirmPw);
    if (pwErr) {
      showToast(pwErr, "error");
      return;
    }
    try {
      const res = await apiRequest("/api/auth/password/reset-confirm", {
        method: "POST",
        body: JSON.stringify({
          phone_number: document.getElementById("reset-phone").value,
          otp_code: document.getElementById("reset-otp").value,
          new_password: pw,
          confirm_password: confirmPw,
        }),
      });
      showToast(res.message, "success");
      showAuthScreen("login");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  return { showAuthScreen };
}
