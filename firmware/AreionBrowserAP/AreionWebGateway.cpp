#include "AreionWebGateway.h"
#include "WebGatewayWire.h"
#include <Arduino.h>
#include <esp_http_server.h>
#include <esp_random.h>
#include <fcntl.h>
#include <lwip/sockets.h>
#include <lwip/tcp.h>
#include <cerrno>
#include <cstring>
#include <new>
#include <unistd.h>

#if !CONFIG_HTTPD_WS_SUPPORT
#error "Use the Arduino ESP32 core with the built-in ESP HTTP Server WebSocket component."
#endif

namespace {
constexpr char ALLOWED_ORIGIN[] = "https://chilchiltrips-boop.github.io";
constexpr char SUBPROTOCOL[] = "areion-link-v2";
struct Peer {
  int socket = -1, udp = -1;
  uint32_t lastPoll = 0;
  gateway::Credits credits;
  bool draining = false;
  uint8_t input[5 + gateway::MAX_FRAME];
  uint8_t output[9 + gateway::BURST * gateway::MAX_FRAME];
};
httpd_handle_t server = nullptr;
in_addr_t apAddress = 0;
uint16_t localPort = 0;
Peer* current = nullptr;  // Only the HTTPD task accesses this pointer.

void dispose(void* context) {
  Peer* p = static_cast<Peer*>(context);
  if (p == current) current = nullptr;
  if (p->udp >= 0) close(p->udp);
  delete p;
}
bool onKitAP(int fd) {
  sockaddr_storage local{};
  socklen_t size = sizeof(local);
  if (getsockname(fd, reinterpret_cast<sockaddr*>(&local), &size)) return false;
  if (local.ss_family == AF_INET)
    return reinterpret_cast<sockaddr_in*>(&local)->sin_addr.s_addr == apAddress;
#if defined(AF_INET6)
  // ESP HTTPD may use a dual-stack listening socket even for an IPv4 client.
  if (local.ss_family == AF_INET6) {
    static const uint8_t prefix[12] = {0,0,0,0,0,0,0,0,0,0,0xff,0xff};
    const auto* addr = reinterpret_cast<sockaddr_in6*>(&local)->sin6_addr.s6_addr;
    return !memcmp(addr, prefix, 12) && !memcmp(addr + 12, &apAddress, 4);
  }
#endif
  return false;
}
bool allowed(httpd_req_t* req) {
  char origin[96], protocol[32];
  return onKitAP(httpd_req_to_sockfd(req))
      && httpd_req_get_hdr_value_str(req, "Origin", origin, sizeof(origin)) == ESP_OK
      && strcmp(origin, ALLOWED_ORIGIN) == 0
      && httpd_req_get_hdr_value_str(req, "Sec-WebSocket-Protocol", protocol, sizeof(protocol)) == ESP_OK
      && strcmp(protocol, SUBPROTOCOL) == 0;
}

esp_err_t attach(httpd_req_t* req) {
  if (!allowed(req)) return ESP_FAIL;
  // A closed radio/browser can leave a TCP socket until retransmission times
  // out. An expired gateway cannot extend the flight controller's owner lease.
  if (current) {
    if (uint32_t(millis() - current->lastPoll) <= 1000) return ESP_FAIL;
    if (httpd_sess_trigger_close(server, current->socket) != ESP_OK) return ESP_FAIL;
  }
  Peer* p = new(std::nothrow) Peer;
  if (!p) return ESP_ERR_NO_MEM;
  p->socket = httpd_req_to_sockfd(req);
  const int noDelay = 1;
  setsockopt(p->socket, IPPROTO_TCP, TCP_NODELAY, &noDelay, sizeof(noDelay));
  p->udp = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  sockaddr_in destination{};
  destination.sin_family = AF_INET;
  destination.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  destination.sin_port = htons(localPort);
  if (p->udp < 0 || fcntl(p->udp, F_SETFL, O_NONBLOCK) < 0
      || connect(p->udp, reinterpret_cast<sockaddr*>(&destination), sizeof(destination)) < 0) {
    dispose(p); return ESP_FAIL;
  }
  p->lastPoll = millis();
  req->sess_ctx = current = p;
  req->free_ctx = dispose;
  return ESP_OK;
}

esp_err_t reply(httpd_req_t* req, Peer& p, uint32_t id, uint32_t now) {
  uint32_t ticket = esp_random();
  if (!ticket) ticket = 1;
  if (uint32_t(now - p.lastPoll) > gateway::MAX_POLL_GAP_MS) {
    p.credits = gateway::Credits{};
    p.draining = true;
  }
  p.credits.issue(ticket, now);
  p.lastPoll = now;
  p.output[0] = gateway::REPLY;
  gateway::write32(p.output + 1, id);
  gateway::write32(p.output + 5, ticket);
  size_t used = 9;
  for (unsigned i = 0; i < gateway::BURST; ++i) {
    const int n = recv(p.udp, p.output + used, gateway::MAX_FRAME, 0);
    if (n < 0) {
      if (errno == EAGAIN || errno == EWOULDBLOCK) { p.draining = false; break; }
      return ESP_FAIL;
    }
    if (!p.draining && n && p.output[used] == '$' && p.output[used + n - 1] == '\n') used += n;
  }
  httpd_ws_frame_t response{};
  response.type = HTTPD_WS_TYPE_BINARY;
  response.payload = p.output;
  response.len = used;
  return httpd_ws_send_frame(req, &response);
}

esp_err_t receive(httpd_req_t* req) {
  if (req->method == HTTP_GET) return attach(req);
  Peer* p = static_cast<Peer*>(req->sess_ctx);
  if (!p || p != current) return ESP_FAIL;
  httpd_ws_frame_t frame{};
  if (httpd_ws_recv_frame(req, &frame, 0) != ESP_OK || frame.type != HTTPD_WS_TYPE_BINARY
      || !frame.final || frame.len < 5 || frame.len > sizeof(p->input)) return ESP_FAIL;
  frame.payload = p->input;
  if (httpd_ws_recv_frame(req, &frame, sizeof(p->input)) != ESP_OK) return ESP_FAIL;
  const uint32_t now = millis(), value = gateway::read32(p->input + 1);
  if (p->input[0] == gateway::POLL && frame.len == 5) return reply(req, *p, value, now);
  if (p->input[0] != gateway::FRAME || frame.len <= 5
      || p->input[5] != '$' || p->input[frame.len - 1] != '\n') return ESP_FAIL;
  // Late commands are discarded. A later poll can still obtain current telemetry.
  if (p->draining || !p->credits.valid(value, now) || uint32_t(now - p->lastPoll) > gateway::MAX_POLL_GAP_MS) return ESP_OK;
  const size_t bytes = frame.len - 5;
  const int sent=send(p->udp, p->input + 5, bytes, 0);
  if (sent < 0 && (errno==EAGAIN || errno==EWOULDBLOCK || errno==ENOBUFS || errno==ENOMEM)) return ESP_OK;
  return sent == int(bytes) ? ESP_OK : ESP_FAIL;
}
} // namespace

bool areion_web_gateway_begin(IPAddress ap, uint16_t udpPort) {
  if (server) return true;
  localPort = udpPort;
  apAddress = uint32_t(ap);
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 8081;
  config.max_open_sockets = 2;
  config.task_priority = 1;
  config.recv_wait_timeout = 1;
  config.send_wait_timeout = 1;
  if (httpd_start(&server, &config) != ESP_OK) { server = nullptr; return false; }
  httpd_uri_t route{};
  route.uri = "/areion";
  route.method = HTTP_GET;
  route.handler = receive;
  route.is_websocket = true;
  route.supported_subprotocol = SUBPROTOCOL;
  if (httpd_register_uri_handler(server, &route) == ESP_OK) return true;
  httpd_stop(server);
  server = nullptr;
  return false;
}
