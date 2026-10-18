import type { IconProps } from "@opal/types";

// Mail.ru app icon. The colors are inlined (like the other brand logos) so
// the mark renders identically in both themes. The background has app-icon
// corners (radius 20% of the side, as the LM Studio logo).
const SvgMailru = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 32 32"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <title>Mail.ru</title>
    <rect width="32" height="32" rx="6.4" fill="#07F" />
    <path
      fill="#fff"
      d="M19.008 16A3.01 3.01 0 0 1 16 19.008 3.01 3.01 0 0 1 12.992 16 3.01 3.01 0 0 1 16 12.992 3.01 3.01 0 0 1 19.008 16M16 6C10.486 6 6 10.486 6 16s4.486 10 10 10c2.02 0 3.968-.601 5.633-1.74l.029-.02-1.348-1.566-.022.015A7.9 7.9 0 0 1 16 23.95c-4.384 0-7.95-3.566-7.95-7.95S11.616 8.05 16 8.05s7.95 3.566 7.95 7.95a8 8 0 0 1-.187 1.709c-.252 1.032-.974 1.348-1.517 1.306-.545-.044-1.183-.433-1.188-1.384V16A5.063 5.063 0 0 0 16 10.942 5.063 5.063 0 0 0 10.942 16 5.063 5.063 0 0 0 16 21.058c1.355 0 2.626-.53 3.584-1.493a3.25 3.25 0 0 0 2.767 1.504c.727 0 1.448-.243 2.03-.685.599-.455 1.046-1.113 1.294-1.903.04-.128.112-.42.113-.422l.001-.01C25.935 17.413 26 16.78 26 16c0-5.514-4.486-10-10-10"
    />
  </svg>
);
export default SvgMailru;
