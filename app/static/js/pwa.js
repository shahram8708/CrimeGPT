(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  var installBtn = document.getElementById("btn-install-app");
  var deferred = null;
  var isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
  var isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;

  if (installBtn && !isStandalone) {
    installBtn.classList.add("d-none");
    window.addEventListener("beforeinstallprompt", function (e) {
      e.preventDefault();
      deferred = e;
      installBtn.classList.remove("d-none");
    });
    installBtn.addEventListener("click", function () {
      if (!deferred) return;
      deferred.prompt();
      deferred.userChoice.finally(function () {
        deferred = null;
        installBtn.classList.add("d-none");
      });
    });
  }

  var hint = document.getElementById("ios-install-hint");
  if (hint && isIos && !isStandalone) {
    if (!window.sessionStorage.getItem("iosHintDismissed")) hint.classList.remove("d-none");
    var close = document.getElementById("ios-hint-dismiss");
    if (close) {
      close.addEventListener("click", function () {
        hint.classList.add("d-none");
        window.sessionStorage.setItem("iosHintDismissed", "1");
      });
    }
  }
})();
