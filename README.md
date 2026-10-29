# PC Remote

Contrôle ton PC depuis ton mobile : écran en direct, souris, clavier, commandes shell et ton IA.

## Lancer (Windows)
1. Double-clique `start.bat` (installe tout au premier lancement).
2. Autorise le pare-feu Windows en **réseau privé** quand il le demande.
3. Scanne le QR code affiché (ou ouvre l'URL « Sur le mobile ») avec ton téléphone, sur le même Wi-Fi.
4. Sur le téléphone : menu du navigateur > « Ajouter à l'écran d'accueil » pour l'avoir comme une app.

Mac/Linux : `pip install -r requirements.txt` puis `python server.py`.

## Utilisation
- **Écran** : ▶ Écran lance la capture en direct (Éco / Normal / HD).
  - 1 doigt = déplacer la souris (mode Trackpad) ou pointer directement (mode Direct)
  - tap = clic gauche, tap à 2 doigts = clic droit, 2 doigts qui glissent = défiler
  - Glisser = maintient le clic (drag & drop)
  - ⌨ Clavier = texte (accents OK) + touches spéciales et raccourcis
- **IA** : ton message est envoyé sur stdin à la commande `AI_CMD` (défaut `claude -p`), la réponse arrive en direct.
  Change-la dans `start.bat`, ex. `set AI_CMD=ollama run llama3` ou `set AI_CMD=python mon_agent.py`.
  Dossier de travail : variable `WORKDIR` (défaut : ton dossier utilisateur).
- **Shell** : exécute une commande directement sur le PC.

## Sécurité (important)
Cette app donne le contrôle total du PC. Le token (fichier `token.txt`) protège l'accès : ne le partage pas,
supprime `token.txt` pour en générer un nouveau. Ne l'expose pas sur internet (pas de redirection de port).
Pour l'utiliser hors de la maison, installe Tailscale sur le PC et le téléphone et utilise l'IP Tailscale du PC.
