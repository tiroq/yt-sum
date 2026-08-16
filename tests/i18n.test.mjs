import test from "node:test";
import assert from "node:assert/strict";

import { DEFAULT_UI_LANGUAGE, SUPPORTED_UI_LANGUAGES, UI_TEXT, createUiDictionary, getUiText, isSupportedUiLanguage } from "../app/i18n.js";

test("ui translations are centralized and support default fallback", () => {
  assert.deepEqual(SUPPORTED_UI_LANGUAGES, ["ru", "en"]);
  assert.equal(isSupportedUiLanguage("ru"), true);
  assert.equal(isSupportedUiLanguage("fr"), false);

  const ru = createUiDictionary("ru");
  const en = createUiDictionary("en");

  assert.equal(ru.library, "Библиотека");
  assert.equal(en.library, "Library");
  assert.equal(getUiText("fr", "library"), UI_TEXT[DEFAULT_UI_LANGUAGE].library);
  assert.equal(getUiText("en", "summary"), "Summary");
});
