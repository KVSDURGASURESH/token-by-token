import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/oswald";
import "./public-site.css";
import { PublicSite } from "./PublicSite";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PublicSite />
  </StrictMode>,
);
