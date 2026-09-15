import { app } from '../../../../scripts/app.js';

// Wheel turns and middle-button drags over the panel reach the canvas, as they do over ComfyUI's multiline text
// widgets; left clicks and keys stay on the panel so a row press cannot drag the node and Delete cannot remove it.
export function forwardToCanvas(body) {
  body.addEventListener('keydown', (event) => event.stopPropagation());
  body.addEventListener('pointerdown', (event) => {
    if (event.button === 1 || event.buttons === 4) app.canvas?.processMouseDown(event);
    event.stopPropagation();
  });
  body.addEventListener('pointermove', (event) => {
    if ((event.buttons & 4) === 4) app.canvas?.processMouseMove(event);
  });
  body.addEventListener('pointerup', (event) => {
    if (event.button === 1) app.canvas?.processMouseUp(event);
  });
  body.addEventListener('wheel', (event) => {
    event.preventDefault();
    app.canvas?.processMouseWheel(event);
  });
}
// An overflowing list keeps a plain vertical wheel for scrolling; Ctrl and horizontal turns still reach the canvas.
export function keepScrollWheel(event) {
  const list = event.currentTarget;
  if (!event.ctrlKey && Math.abs(event.deltaX) <= Math.abs(event.deltaY) && list.scrollHeight > list.clientHeight) event.stopPropagation();
}
