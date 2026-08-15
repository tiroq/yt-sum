/* global chrome */
import { DEFAULT_SETTINGS, serviceEndpoint } from "./api-client.js";
const form = document.querySelector("#settings-form");
const serviceUrl = document.querySelector("#service-url");
const authorizationToken = document.querySelector("#authorization-token");
const status = document.querySelector("#status");
const saved = await chrome.storage.sync.get(DEFAULT_SETTINGS);
serviceUrl.value = saved.serviceUrl;
authorizationToken.value = saved.authorizationToken;
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try { serviceEndpoint(serviceUrl.value); await chrome.storage.sync.set({ serviceUrl: serviceUrl.value.trim().replace(/\/$/, ""), authorizationToken: authorizationToken.value }); status.textContent = "Settings saved."; }
  catch (error) { status.textContent = error.message || "Could not save settings."; }
});
