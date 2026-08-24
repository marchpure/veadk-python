import "./styles.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { MotionConfig } from "motion/react";
import { PhotoProvider } from "react-photo-view";
import "react-photo-view/dist/react-photo-view.css";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MotionConfig reducedMotion="user">
      <PhotoProvider maskOpacity={0.9}>
        <App />
      </PhotoProvider>
    </MotionConfig>
  </React.StrictMode>,
);
