import React from "react";
import type { IconProps } from "@opal/types";

// Yandex Mail app icon (2026). The colors are inlined (like the other brand
// logos) so the mark renders identically in both themes. The clip rounds the
// corners like an app icon (radius 20% of the side, as the LM Studio logo).
const SvgYandexMail = ({ size, ...props }: IconProps) => {
  const clipId = React.useId();
  const flapGradientId = React.useId();
  const shineGradientId = React.useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <title>Yandex Mail</title>
      <g clipPath={`url(#${clipId})`}>
        <path fill="#FFCA38" d="M0 0h40v40H0z" />
        <path
          fill="#FFDC7C"
          d="M40 32.994V40H0v-7.463L17.78 17.72a3.04 3.04 0 0 1 3.891 0z"
        />
        <path
          fill={`url(#${flapGradientId})`}
          d="M40 8.565 22.018 24.578a3.04 3.04 0 0 1-4.038.005L0 8.638V0h40z"
        />
        <path
          fill={`url(#${shineGradientId})`}
          fillOpacity=".5"
          d="M40 8.565 22.018 24.578a3.04 3.04 0 0 1-4.038.005L0 8.638V0h40z"
        />
      </g>
      <defs>
        <clipPath id={clipId}>
          <rect width="40" height="40" rx="8" />
        </clipPath>
        <linearGradient
          id={flapGradientId}
          x1="49.479"
          x2="16.304"
          y1="-25.224"
          y2="19.19"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#FFDA3E" />
          <stop offset="1" stopColor="#FC4714" />
        </linearGradient>
        <linearGradient
          id={shineGradientId}
          x1="47.794"
          x2="20.067"
          y1="-3.132"
          y2="21.921"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#fff" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
};
export default SvgYandexMail;
