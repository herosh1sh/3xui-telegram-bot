import React from "react";
import { Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Cabinet from "./pages/Cabinet";
import Admin from "./pages/Admin";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/cabinet" element={<Cabinet />} />
      <Route path="/admin" element={<Admin />} />
    </Routes>
  );
}
