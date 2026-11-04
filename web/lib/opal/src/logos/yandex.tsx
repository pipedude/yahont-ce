import type { IconProps } from "@opal/types";

// Yandex "Я" mark on the red square. The colors are inlined (like the other
// brand logos) so the mark renders identically in both themes. The corners are
// rounded like an app icon (radius 20% of the side, as the Yandex Mail logo).
const SvgYandex = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 18 18"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <title>Yandex</title>
    <rect width="18" height="18" rx="3.6" fill="#FC3F1D" />
    <path
      fill="#fff"
      d="M11.823 14h-1.748V5.354h-.778c-1.428 0-2.176.713-2.176 1.779 0 1.209.516 1.769 1.583 2.482l.879.593-2.527 3.79h-1.88l2.275-3.384C6.143 9.68 5.407 8.769 5.407 7.23 5.407 5.308 6.747 4 9.284 4h2.527v9.997h.012z"
    />
  </svg>
);
export default SvgYandex;
