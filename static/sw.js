// Service worker mínimo: só precisa receber pushes e mostrar notificações.
self.addEventListener("push", (event) => {
  let data = { title: "Raro Tracker", body: "Atualização disponível", url: "/" };
  try {
    if (event.data) data = event.data.json();
  } catch (e) {
    /* payload não era JSON, usa default */
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/icons/icon-192.png",
      data: { url: data.url },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(clients.openWindow(url));
});
