# Arisu Example

Inverts the input image. Placeholder node from the project scaffold.

## Inputs

| Parameter         | Type   | Description                                      |
|-------------------|--------|--------------------------------------------------|
| `image`           | IMAGE  | Image batch to invert                            |
| `int_field`       | INT    | An integer parameter (0-4096, step 64)           |
| `float_field`     | FLOAT  | A float parameter (0.0-10.0, step 0.01)          |
| `print_to_screen` | COMBO  | `enable` / `disable` logging of the widget values |
| `string_field`    | STRING | A text parameter                                 |

## Outputs

| Output  | Type  | Description        |
|---------|-------|--------------------|
| `image` | IMAGE | The inverted image |
