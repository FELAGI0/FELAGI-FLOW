import { act } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

test("renders Felagi Flow heading", () => {
  const div = document.createElement("div");
  const root = createRoot(div);
  act(() => {
    root.render(<App />);
  });
  expect(div.textContent).toContain("Felagi Flow");
});
