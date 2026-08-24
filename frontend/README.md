# DataAgent Frontend

The user interface for **DataAgent-MCP**.

---

## ⚙️ Prerequisites

- **Node.js**: v18+ (if using Next.js / Vite / React)
- **npm** / **yarn** / **pnpm** (or Python if using Streamlit)

---

## 🚀 Setup & Development

### 1. Install Dependencies

From the `frontend/` directory:

```bash
npm install
```

### 2. Environment Configuration

Create a `.env.local` file in `frontend/`:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

### 3. Run Development Server

```bash
npm run dev
```

The application will be available at [http://localhost:3000](http://localhost:3000) (or the port specified by your frontend framework).
