# Publicar no servidor e embutir no Teams

Receita do modo externo: o `dashboard.html` fica parado no servidor e o
`dados.json` é regerado a cada coleta. Quem abre a aba no Teams sempre vê os
números da última geração, sem ninguém baixar nada.

## 1. Gerar os dois arquivos

```bash
python gerar_dashboard.py --modo externo -o C:\inetpub\telemetria\dashboard.html
```

Isso escreve `dashboard.html` e `dados.json` **na mesma pasta**. Os dois
precisam ficar juntos no servidor: a página busca o JSON por caminho relativo.

Para atualizar depois, é o mesmo comando — o HTML é reescrito igual e só o JSON
muda de conteúdo.

## 2. Servir a pasta por HTTPS

O Teams só embute HTTPS com certificado válido. Certificado autoassinado faz a
aba ficar em branco, sem mensagem de erro.

### nginx

```nginx
server {
    listen 443 ssl;
    server_name telemetria.suaintranet.gov.br;

    ssl_certificate     /etc/ssl/certs/intranet.crt;
    ssl_certificate_key /etc/ssl/private/intranet.key;

    root /var/www/telemetria;
    index dashboard.html;

    # Sem isto o Teams mostra uma aba em branco.
    add_header Content-Security-Policy "frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com https://*.skype.com" always;

    # O JSON nunca pode vir do cache, senão "sempre atualizado" vira mentira.
    location = /dados.json {
        add_header Cache-Control "no-store" always;
        default_type application/json;
    }

    location = /dashboard.html {
        add_header Cache-Control "no-cache" always;
    }
}
```

### IIS

Crie um `web.config` na pasta publicada:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <httpProtocol>
      <customHeaders>
        <!-- Se algum GPO/módulo adicionar X-Frame-Options, remova aqui: -->
        <remove name="X-Frame-Options" />
        <add name="Content-Security-Policy"
             value="frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com https://*.skype.com" />
      </customHeaders>
    </httpProtocol>
    <staticContent>
      <remove fileExtension=".json" />
      <mimeMap fileExtension=".json" mimeType="application/json" />
    </staticContent>
  </system.webServer>
</configuration>
```

Se o site estiver com Autenticação do Windows, teste **de dentro do Teams**, não
só no navegador: o prompt de credencial dentro do iframe costuma falhar. Para
um dashboard sem dado pessoal, autenticação anônima restrita por rede costuma
ser mais simples e funciona melhor embutido.

## 3. Adicionar a aba no Teams

No canal: **+** (Adicionar uma guia) → **Site** → cole a URL
`https://telemetria.suaintranet.gov.br/dashboard.html` → dê um nome à guia.

Se a aba abrir em branco, é quase sempre uma destas três:

| Sintoma | Causa provável |
|---|---|
| Branco total, sem erro | servidor mandando `X-Frame-Options`, ou faltando o `frame-ancestors` |
| Erro de certificado | HTTPS autoassinado ou cadeia incompleta |
| Pede login e não sai do lugar | autenticação integrada não sobrevive ao iframe |

O app "Site" pode estar bloqueado por política do tenant. Se não aparecer na
lista de guias, é com quem administra o M365.

## 4. Agendar a atualização

Na máquina que enxerga `\\ger-sinet\telemetria` e consegue escrever na pasta do
servidor:

```bash
schtasks /create /tn "Dashboard telemetria" /tr "python C:\scripts\web\gerar_dashboard.py --modo externo -o C:\inetpub\telemetria\dashboard.html" /sc daily /st 07:00
```

Alinhe o horário com a coleta: regerar de hora em hora não deixa o dado mais
novo se o CSV chega uma vez por semana.

## Os dois modos, lado a lado

| | `--modo embutido` (padrão) | `--modo externo` |
|---|---|---|
| Arquivos | 1 | 2, na mesma pasta |
| Abre do disco | sim | não (o navegador bloqueia o fetch em `file://`) |
| Vai por e-mail | sim | não |
| Serve para aba do Teams | não | sim |
| Atualizar | reenviar o arquivo | regerar o JSON no servidor |

Dá para usar os dois: o externo alimenta a aba do Teams, e o embutido é o que
você anexa num e-mail ou leva para uma reunião sem rede.
