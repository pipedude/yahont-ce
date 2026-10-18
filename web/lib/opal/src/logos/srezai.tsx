import React from "react";
import type { IconProps } from "@opal/types";

// srezai.ru mark: a dark circle with "AI" and the green slanted "cut".
// Source: nodes/Srezai/node_logo.svg in github.com/srezai-team/n8n-nodes-srezai
// (MIT). The colors are inlined (like the other brand logos) so the mark
// renders identically in both themes.
const SvgSrezai = ({ size, ...props }: IconProps) => {
  const maskId = React.useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 31 30"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <title>srezai.ru</title>
      <path
        d="M31 15C31 23.2843 24.0604 30 15.5 30C6.93959 30 0 23.2843 0 15C0 6.71573 6.93959 0 15.5 0C24.0604 0 31 6.71573 31 15Z"
        fill="black"
      />
      <path
        d="M11.4097 20H9.05127L13.0283 9.33594H14.5078L14.3174 11.2549L11.4097 20ZM13.79 11.2549L13.5776 9.33594H15.0718L19.0635 20H16.7124L13.79 11.2549ZM16.6245 17.8101H10.9409V16.0229H16.6245V17.8101ZM22.1716 8.92578C22.5378 8.92578 22.8283 9.03076 23.0432 9.24072C23.258 9.4458 23.3654 9.70947 23.3654 10.0317C23.3654 10.3442 23.258 10.6055 23.0432 10.8154C22.8283 11.0205 22.5378 11.123 22.1716 11.123C21.8103 11.123 21.5222 11.0205 21.3073 10.8154C21.0925 10.6055 20.9851 10.3442 20.9851 10.0317C20.9851 9.70947 21.0925 9.4458 21.3073 9.24072C21.5222 9.03076 21.8103 8.92578 22.1716 8.92578ZM23.2409 20H21.1096V12.0752H23.2409V20Z"
        fill="white"
      />
      <mask
        id={maskId}
        style={{ maskType: "alpha" }}
        maskUnits="userSpaceOnUse"
        x="1"
        y="-5"
        width="15"
        height="32"
      >
        <rect
          x="12.5002"
          y="-4.16083"
          width="3.6037"
          height="31"
          transform="rotate(20.9552 12.5002 -4.16083)"
          fill="#E3B447"
        />
      </mask>
      <g mask={`url(#${maskId})`}>
        <ellipse cx="17.2083" cy="15.063" rx="15.5" ry="15" fill="#4FFD72" />
      </g>
    </svg>
  );
};

export default SvgSrezai;
