# Guide d'Intégration MCP pour Agents AI — OwnBook & Calibre-Web

OwnBook intègre nativement un serveur **Model Context Protocol (MCP)** en HTTP/SSE accessible directement sur l'endpoint `/mcp`.
Il permet à tous vos agents AI en ligne ou locaux (Claude Desktop, Cursor, Antigravity, agents autonomes) de naviguer dans votre bibliothèque, de consulter les tables des matières et d'extraire le texte des livres (EPUB, PDF, MOBI).

---

## 1. Coordonnées du Serveur en Ligne (Contabo Coolify)

- **URL de l'application Web** : `https://ownbook-books.169.58.158.213.sslip.io`
- **Endpoint MCP pour les agents** : `https://ownbook-books.169.58.158.213.sslip.io/mcp`
- **Partage Calibre-Web** : Volume partagé `/data/calibre-web/books` synchronisé en temps réel avec OwnBook via `calibre-sync`.

---

## 2. Authentification et Génération de Jeton (Token)

L'authentification s'effectue via l'API PocketBase d'OwnBook. Les jetons restent valides 5 jours.

### Obtenir un jeton en une ligne de commande :

```bash
TOKEN=$(curl -s -X POST "https://ownbook-books.169.58.158.213.sslip.io/api/collections/users/auth-with-password" \
  -H "Content-Type: application/json" \
  -d '{"identity":"figoro@orchidy.fr","password":"OwnBookSecret2026!"}' | jq -r .token)
echo "Jeton: $TOKEN"
```

---

## 3. Configuration dans vos Outils d'Agents AI

### A. Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "ownbook": {
      "url": "https://ownbook-books.169.58.158.213.sslip.io/mcp",
      "headers": {
        "Authorization": "Bearer VOTRE_JETON_ICI"
      }
    }
  }
}
```

### B. Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "ownbook": {
      "url": "https://ownbook-books.169.58.158.213.sslip.io/mcp",
      "headers": {
        "Authorization": "Bearer VOTRE_JETON_ICI"
      }
    }
  }
}
```

### C. Script d'auto-rafraîchissement automatique du token (Linux / macOS)

Pour éviter l'expiration du token après 5 jours, créez un script exécutable `~/.config/mcp/ownbook-token.sh` :

```bash
#!/usr/bin/env bash
curl -s -X POST "https://ownbook-books.169.58.158.213.sslip.io/api/collections/users/auth-with-password" \
  -H "Content-Type: application/json" \
  -d '{"identity":"figoro@orchidy.fr","password":"OwnBookSecret2026!"}' | jq -r .token
```

Puis dans votre client MCP :
```json
{
  "mcpServers": {
    "ownbook": {
      "url": "https://ownbook-books.169.58.158.213.sslip.io/mcp",
      "auth": "bearer",
      "bearerToken": "!~/.config/mcp/ownbook-token.sh"
    }
  }
}
```

---

## 4. Outils Disponibles pour vos Agents AI

| Outil MCP | Paramètres | Description & Résultat |
| :--- | :--- | :--- |
| `list_books` | Aucun | Renvoie la liste complète des livres avec leur `id`, `title`, `author`, `page_count` et `parse_status`. |
| `get_toc` | `book_id` | Renvoie la table des matières hiérarchique avec les titres des sections et les numéros de page correspondants. |
| `get_section_text` | `book_id`, `section_title`, `start_page` *(opt)* | Extrait le texte complet d'un chapitre/section donné avec curseur de pagination automatique (`next_page`). |
| `get_pages` | `book_id`, `from_page`, `to_page` | Extrait le texte brut paginé pour un intervalle de pages précis. |
| `search_in_book` | `book_id`, `query` | Effectue une recherche plein texte dans tout le livre et renvoie les numéros de page et extraits correspondants. |

---

## 5. Synchronisation et Partage Calibre-Web

- Calibre-Web héberge vos livres originaux dans `/data/calibre-web/books`.
- Le service `calibre-sync` tourne en conteneur compagnon, surveille la bibliothèque Calibre et importe automatiquement tout nouveau livre ajouté dans OwnBook.
- Dès qu'un livre est importé, OwnBook l'analyse, découpe ses pages et extrait son texte, le rendant instantanément interrogeable par vos agents AI.
