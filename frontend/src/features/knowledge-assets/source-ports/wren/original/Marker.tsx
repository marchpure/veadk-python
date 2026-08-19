export default function Marker() {
  return (
    <svg className="kc-wren-marker-defs" aria-hidden="true">
      <defs>
        <marker id="many_right" viewBox="0 0 14 22" markerHeight={14} markerWidth={14} refX={0} refY={11}>
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M9.28866 10L0 2.33206V0L13.5547 11L0 22V19.668L9.28864 12H0V10H9.28866Z"
            fill="#b1b1b7"
          />
        </marker>
        <marker id="many_left" viewBox="0 0 14 22" markerHeight={14} markerWidth={14} refX={14} refY={11}>
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M4.26603 12L13.5547 19.6679V22L0 11L13.5547 0V2.33204L4.26605 10H13.5547V12H4.26603Z"
            fill="#b1b1b7"
          />
        </marker>
        <marker id="one_right" viewBox="0 0 14 22" markerHeight={14} markerWidth={14} refX={-4} refY={11}>
          <rect x="6" width="2" height="22" fill="#b1b1b7" />
        </marker>
        <marker id="one_left" viewBox="0 0 14 22" markerHeight={14} markerWidth={14} refX={18} refY={11}>
          <rect x="6" width="2" height="22" fill="#b1b1b7" />
        </marker>
        <marker id="many_right_selected" viewBox="0 0 18 32" markerHeight={18} markerWidth={18} refX={0} refY={16}>
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M13.4161 4.94444L13.2993 8H14.7007L14.5839 4.94444L17.2993 6.58333L18 5.41667L15.1387 4L18 2.58333L17.2993 1.41667L14.5839 3.05556L14.7007 0H13.2993L13.4161 3.05556L10.7007 1.41667L10 2.58333L12.8613 4L10 5.41667L10.7007 6.58333L13.4161 4.94444ZM0 7.33206L9.28865 15H0V17H9.28863L0 24.668V27L13.5547 16L0 5V7.33206Z"
            fill="#2f54eb"
          />
        </marker>
        <marker id="many_left_selected" viewBox="0 0 18 32" markerHeight={18} markerWidth={18} refX={18} refY={16}>
          <path
            fillRule="evenodd"
            clipRule="evenodd"
            d="M3.41606 4.94444L3.29927 8H4.70073L4.58394 4.94444L7.29927 6.58333L8 5.41667L5.13869 4L8 2.58333L7.29927 1.41667L4.58394 3.05556L4.70073 0H3.29927L3.41606 3.05556L0.70073 1.41667L0 2.58333L2.86131 4L0 5.41667L0.70073 6.58333L3.41606 4.94444ZM17.8899 24.6679L8.60127 17H17.8899V15H8.60129L17.8899 7.33204V5L4.33524 16L17.8899 27V24.6679Z"
            fill="#2f54eb"
          />
        </marker>
      </defs>
    </svg>
  );
}
