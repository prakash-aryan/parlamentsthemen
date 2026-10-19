# Web front end

Next.js (App Router, TypeScript) front end for the parltopics API.

```bash
npm ci
npm run build    # static export in out/, served by the API at /
npm run dev      # development server on port 3000, talks to the API on port 8765
```

`NEXT_PUBLIC_API_BASE` sets the API address. It is empty for the build, so the exported page calls the API on its own origin, and `.env.development` points the development server at `http://localhost:8765`.
