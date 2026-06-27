// Registra o service worker assim que a página carrega (idempotente).
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch((err) => {
    console.warn("Falha ao registrar service worker:", err);
  });
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

window.subscribeToPush = async function () {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    alert("Seu navegador não suporta notificações push.");
    return;
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    alert("Permissão de notificação negada.");
    return;
  }

  const vapidKey = window.VAPID_PUBLIC_KEY;
  if (!vapidKey) {
    alert("VAPID_PUBLIC_KEY não configurada no servidor — notificações push desativadas.");
    return;
  }

  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidKey),
  });

  const response = await fetch("/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });

  if (response.ok) {
    alert("Notificações ativadas neste navegador! 🔔");
  } else {
    alert("Não foi possível registrar a inscrição no servidor.");
  }
};
