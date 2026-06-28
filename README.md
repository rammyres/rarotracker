# Raro Tracker

Rastreador de disponibilidade de edições raras/especiais de livros, com
checagem automática 3x/dia, alerta por e-mail e notificação push no
navegador, e estimativa de frete para o Brasil.

## Como funciona

1. **Adicionar livro** (`/add`): você informa título e autor (ou já o ISBN,
   se souber). O app consulta a Google Books API e a Open Library para
   listar as edições existentes com ISBN.
2. **Clarificação** (`/clarify/<id>`): você escolhe a edição canônica certa
   entre as opções encontradas (ou informa o ISBN manualmente, se nenhuma
   bater). Isso evita rastrear a edição errada.
3. **Monitoramento**: a cada checagem (manual ou agendada), o app:
   - Procura o produto correspondente em cada loja Shopify monitorada
     (The Broken Binding, FairyLoot, Illumicrate, OwlCrate, Goldsboro Books)
     via `/search/suggest.json` e `/products.json` (endpoints públicos,
     sem autenticação), casando pelo ISBN no campo `barcode` da variante
     sempre que possível.
   - Estima o frete até o Brasil usando a Storefront GraphQL API (também
     pública/tokenless) simulando um carrinho com endereço de entrega BR.
   - Para a Amazon, apenas monta um link de busca por ISBN — a Product
     Advertising API exige histórico de vendas de afiliado, então não é
     viável para um app novo; e fazer scraping violaria os termos de uso
     da Amazon. Essas linhas aparecem como "verificar manualmente".
4. **Alertas**: quando um livro passa de "não disponível" para
   "disponível" em algum site, dispara e-mail (SMTP) e push no navegador
   (Web Push/VAPID) com o link direto do produto.
5. **Checagem agendada**: `scheduler/check_availability.py` é pensado para
   rodar via systemd timer 3x/dia (unidades prontas em `deploy/`).

## Setup local

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python3 deploy/setup_env.py
# assistente interativo: gera SECRET_KEY, configura e-mail (SMTP ou
# sendmail local) e VAPID, escreve .env automaticamente.
# (alternativa manual: cp .env.example .env e edite à mão)

python3 app.py
# abre em http://localhost:5050
```

Pode rodar `python3 deploy/setup_env.py` de novo quando quiser mudar algo
— ele pergunta antes de sobrescrever e faz backup do `.env` anterior.

### E-mail: SMTP ou sendmail local — qual escolher?

- **SMTP** é a opção mais simples se você já tem uma conta de e-mail
  (Gmail, etc) ou um serviço como Resend/SendGrid. Funciona de qualquer
  servidor, sem precisar configurar nada além de host/usuário/senha.
- **sendmail local** usa o MTA do próprio servidor (Postfix/Exim/msmtp).
  Não precisa de credenciais, mas a entregabilidade depende do servidor
  ter reverse DNS, SPF e idealmente DKIM configurados — sem isso, os
  e-mails tendem a cair em spam ou ser rejeitados pelo destinatário.
  Bom se o servidor já envia e-mail para outras coisas (ex: relatórios
  de cron) e você confia na configuração existente.

Pra trocar depois, só editar `EMAIL_BACKEND=smtp` ou `EMAIL_BACKEND=sendmail`
no `.env` (ou rodar o assistente de novo) — nenhum código precisa mudar.

## Deploy (systemd, mesmo padrão dos outros projetos)

Este projeto assume deploy em `/opt/rarotracker`, rodando como o usuário
`ubuntu` (padrão das imagens da OCI — troque `User=`/`Group=` nas
unidades em `deploy/` se usar outro usuário).

```bash
sudo mkdir -p /opt/rarotracker
sudo chown ubuntu:ubuntu /opt/rarotracker
# copie/extraia o projeto pra /opt/rarotracker, depois:
cd /opt/rarotracker
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 deploy/setup_env.py

sudo cp deploy/raro-tracker.service /etc/systemd/system/
sudo cp deploy/raro-tracker-check.service /etc/systemd/system/
sudo cp deploy/raro-tracker-check.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now raro-tracker.service
sudo systemctl enable --now raro-tracker-check.timer

# verificar:
sudo systemctl status raro-tracker.service
systemctl list-timers raro-tracker-check.timer
journalctl -u raro-tracker-check.service -f
```

O timer roda às 08:00, 14:00 e 20:00 (horário local do servidor) — ajuste
o `OnCalendar=` em `deploy/raro-tracker-check.timer` se quiser outros
horários.

`raro-tracker.service` deixa o gunicorn escutando só em `127.0.0.1:5050`
de propósito — ele não é pra ser acessado direto de fora, só através do
Caddy (próxima seção). Isso evita expor a aplicação sem TLS e é exigência
do navegador pra notificação push funcionar.

## Acesso de qualquer lugar com HTTPS (Caddy)

Você não precisa de domínio próprio pra isso. Usamos o **sslip.io**, um
serviço de DNS gratuito e sem cadastro: `137-131-176-138.sslip.io`
resolve automaticamente pro IP `137.131.176.138` (o IP fica embutido no
próprio nome). Pro Let's Encrypt, isso é um domínio público normal, então
o Caddy consegue tirar certificado real sem você configurar nada de DNS.

```bash
# instalar o Caddy (repositório oficial — confirmado atual em 2026)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

# editar deploy/Caddyfile trocando o IP pro seu, depois:
sudo cp /opt/rarotracker/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Depois disso, `https://<seu-ip-com-hifens>.sslip.io` funciona de qualquer
lugar — celular, outra rede, etc — com certificado válido (sem aviso de
"site não seguro" no navegador), e o 🔔 de notificação push passa a
funcionar porque o navegador já está num contexto seguro.

### Ajustar firewall: trocar 5050 por 80/443

Com o Caddy no meio, a porta 5050 não precisa mais ficar aberta pro mundo
— só 80 (challenge do Let's Encrypt + redirect) e 443 (HTTPS). Reverta a
regra de teste que você abriu antes:

```bash
# remove a regra de teste da porta 5050 (se você adicionou uma)
sudo iptables -D INPUT -p tcp --dport 5050 -j ACCEPT

# abre 80 e 443
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

E no console da OCI: na Security List, remova a regra de ingresso pra
5050 e adicione regras pra 80 e 443 (TCP, origem `0.0.0.0/0`).

## Configurar e-mail (SMTP)

Qualquer provedor SMTP funciona — preencha `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD` no `.env`. Com Gmail, use uma "Senha de app"
(precisa de verificação em 2 etapas ativa na conta), não a senha normal.

## Configurar notificação push do navegador

1. Gere as chaves: `python3 deploy/generate_vapid_keys.py`
2. Cole `VAPID_PRIVATE_KEY` e `VAPID_PUBLIC_KEY` no `.env`
3. Reinicie o app, abra a página de um livro e clique em
   "🔔 Ativar notificação no navegador" — o navegador vai pedir permissão.

## Configurar Telegram (gratuito)

1. No Telegram, fale com **@BotFather**, envie `/newbot` e siga as
   instruções (nome, username terminando em `bot`). Ele te dá um token
   tipo `123456789:AAFake-Token-Aqui`.
2. Pra achar seu `chat_id`: mande qualquer mensagem para o bot que você
   acabou de criar, depois abra no navegador:
   `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`
   — o `chat_id` aparece no JSON retornado (`message.chat.id`).
   Alternativa mais simples: fale com **@userinfobot**, ele te devolve
   seu próprio chat ID direto.
3. Cole `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env` (ou rode o
   assistente `deploy/setup_env.py`, que já pergunta isso).

Esse canal usa só uma chamada HTTP simples à Bot API (sem precisar da lib
`python-telegram-bot`, já que aqui só enviamos mensagens, não recebemos
comandos) — então não conflita com nenhum outro bot Telegram que você já
tenha rodando.

## Adicionando uma nova loja Shopify

Não precisa escrever código novo — insira uma linha em `adapters/registry.py`
(`DEFAULT_SOURCES`) com `kind="shopify"` e o domínio, ou insira direto na
tabela `sources` do banco. O adapter genérico cuida do resto.

## Limitações conhecidas / coisas para ficar de olho

- **Amazon**: sem checagem automática (ver acima). Os links de busca por
  ISBN já filtram bastante, mas a conferência final é manual.
- **Frete**: a Storefront GraphQL tokenless funciona na maioria das lojas
  Shopify recentes, mas algumas configurações de loja podem exigir um
  Storefront Access Token (app privado). Quando isso acontece, o app não
  quebra — só registra "verificar no checkout" na coluna de frete daquele
  site. Se quiser, é possível depois gerar um Storefront Access Token por
  loja (gratuito, via app privado no admin da loja) e passar via env var
  para remover essa limitação — não implementado aqui para manter o setup
  inicial simples (zero credenciais).
- **Conversão de moeda**: quando o frete estimado não vem em BRL, o app
  mostra o valor na moeda original (não faz conversão automática, para
  evitar mostrar um número de câmbio desatualizado/impreciso).
- **Matching por título**: a busca via `/search/suggest.json` usa
  similaridade de texto (limiar de 45%) e cai para varredura de
  `/products.json` por ISBN exato como fallback. Em catálogos muito
  grandes, a varredura é limitada a 8 páginas (2000 produtos) por
  checagem, para não sobrecarregar a loja nem a sua própria checagem.
- Testado neste ambiente apenas com respostas simuladas (mocks) das APIs —
  o sandbox de desenvolvimento não tem acesso de rede aos domínios reais
  (Shopify, Google Books, Amazon). Recomendo testar a primeira rodada
  manualmente (`/book/<id>/check-now`) depois do deploy real, antes de
  confiar 100% no agendamento automático.
